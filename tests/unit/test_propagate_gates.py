"""Downstream propagation: the tier is DERIVED, never chosen (T021b, T064).

The dangerous action here is writing a BLOCKING gate into a repo that has
pre-existing violations. That repo gets a gate which is red on its first run,
and a gate nobody can make green is indistinguishable from no gate at all —
markdownlint's 2541-finding entry is this repo's own record of it.

So `tier` is a pure function of the measured baseline with NO override flag,
and these tests weight that direction. The anti-vacuous half matters too: a
propagator that made everything advisory would satisfy every safety test here
while shipping a portfolio that can never fail.

Measured on the real fleet 2026-08-16 — mtg-cube-ai 0 (blocking),
companion-ai 4 (advisory) — so the derivation is load-bearing, not theoretical.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import propagate_gates as pg
import pytest


def _t(baseline):
    return pg.Target(path=Path("/tmp/example"), baseline=baseline)


# --- the derivation ----------------------------------------------------------


def test_a_zero_baseline_enters_blocking():
    """At zero there is no backlog to grant amnesty to, and a report-only check
    over a clean baseline is where checkers go to die."""
    assert _t(0).tier == "blocks"


@pytest.mark.parametrize("baseline", [1, 4, 2541])
def test_any_nonzero_baseline_enters_advisory(baseline):
    """The case that protects other people's repos. companion-ai measured 4."""
    assert _t(baseline).tier == "advisory"


def test_an_UNMEASURED_baseline_enters_advisory_not_blocking():
    """"We could not measure it" must never resolve in favour of the stricter
    setting — that is how a repo gets a red gate it never agreed to. Unknown
    fails toward the safe side, which here is the LESS strict one."""
    assert _t(None).tier == "advisory"


def test_there_is_no_override_flag():
    """The guarantee is structural, not a default.

    A `--force-blocking` escape hatch would be used exactly when the baseline is
    inconvenient, which is exactly when it must not be.
    """
    import ast
    import inspect

    # The REGISTERED FLAGS, not a substring search of the source. My first
    # version grepped the whole module and tripped on its own docstring, which
    # mentions `--force` in order to say it does not exist. Matching text where
    # the structure is what matters — the same error this repo has now recorded
    # five times, here inside the test asserting a safety property.
    tree = ast.parse(inspect.getsource(pg))
    registered = [
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "add_argument"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]
    assert registered, "no CLI flags found — this parse has gone stale"
    offenders = [f for f in registered if "force" in f or "block" in f]
    assert not offenders, (
        f"a flag overriding the tier derivation is registered: {offenders}. "
        f"An escape hatch would be used exactly when the baseline is "
        f"inconvenient, which is exactly when it must not be."
    )


def test_the_reason_is_stated_not_just_the_tier():
    """A propagated gates.yml lands in a repo whose owner did not run this. It
    has to explain why it is set the way it is, or the first person to read it
    assumes it was copied from the trunk."""
    assert "no backlog" in _t(0).reason
    assert "red on day one" in _t(4).reason
    assert "not measured" in _t(None).reason


# --- measurement failures must never read as clean ---------------------------


def test_a_failed_scan_returns_None_not_zero(tmp_path, monkeypatch):
    """`0` means "measured, and clean". A crashed scan that returned 0 would
    promote a gate to blocking on the strength of a scan that never ran — the
    exact defect this whole portfolio exists to close."""
    monkeypatch.setattr(pg.shutil, "which", lambda _: None)   # ast-grep absent
    assert pg.measure(tmp_path, tmp_path / "rule.yml") is None


def test_a_nonzero_ast_grep_exit_returns_None(tmp_path, monkeypatch):
    class Fake:
        returncode, stdout, stderr = 2, "", "boom"
    monkeypatch.setattr(pg.shutil, "which", lambda _: "/usr/bin/ast-grep")
    monkeypatch.setattr(pg.subprocess, "run", lambda *a, **k: Fake())
    assert pg.measure(tmp_path, tmp_path / "rule.yml") is None


def test_unparseable_scan_output_returns_None(tmp_path, monkeypatch):
    class Fake:
        returncode, stdout, stderr = 0, "not json", ""
    monkeypatch.setattr(pg.shutil, "which", lambda _: "/usr/bin/ast-grep")
    monkeypatch.setattr(pg.subprocess, "run", lambda *a, **k: Fake())
    assert pg.measure(tmp_path, tmp_path / "rule.yml") is None


# --- worktrees share a repository --------------------------------------------


def test_a_worktree_is_detected_structurally(tmp_path, monkeypatch):
    """`companion-ai-wt-milestones` is a TOP-LEVEL sibling directory, so a
    path-based `worktrees` filter misses it — which the first dry run of this
    tool duly demonstrated. Writing there would commit the same files twice
    through two checkouts, onto whatever branch that worktree is on."""
    calls = iter(["/repo/.git/worktrees/wt", "/repo/.git"])

    class Fake:
        def __init__(self, out): self.stdout, self.returncode = out, 0

    monkeypatch.setattr(pg.subprocess, "run", lambda *a, **k: Fake(next(calls)))
    assert pg.is_worktree(tmp_path) is True


def test_a_normal_repo_is_not_a_worktree(tmp_path, monkeypatch):
    """Anti-vacuous: treating every repo as a worktree would skip the whole
    fleet and report success."""
    class Fake:
        stdout, returncode = "/repo/.git", 0

    monkeypatch.setattr(pg.subprocess, "run", lambda *a, **k: Fake())
    assert pg.is_worktree(tmp_path) is False


def test_an_unreadable_git_dir_is_treated_as_a_worktree(tmp_path, monkeypatch):
    """Declining to write is always recoverable; writing into a shared checkout
    is not. So 'cannot tell' skips."""
    def boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(pg.subprocess, "run", boom)
    assert pg.is_worktree(tmp_path) is True


# --- the emitted registry must actually load ---------------------------------


def test_the_generated_registry_loads_and_its_proof_resolves(tmp_path):
    """The first draft pointed `failure_proof` at a README.md that does not
    exist. Every propagated gates.yml would have been REFUSED by the registry
    loader (FR-007) — a portfolio that cannot load, shipped to every downstream
    repo. Generating the text is not the same as generating something valid.
    """
    from review_plan_v2.gates.registry import load_registry_file

    target = pg.Target(path=tmp_path, baseline=0)
    (tmp_path / "rules" / "fixtures" / "demo").mkdir(parents=True)
    (tmp_path / "rules" / "demo.yml").write_text("id: demo\nlanguage: typescript\n")
    proof = tmp_path / "rules" / "fixtures" / "demo" / "prove.sh"
    proof.write_text(pg.proof_for("demo"))
    proof.chmod(0o755)
    (tmp_path / "gates.yml").write_text(pg.gates_yml_for(target, "demo"))

    reg = load_registry_file(tmp_path / "gates.yml", repo_root=tmp_path)
    assert reg.gates[0].id == "structural.demo"
    assert reg.gates[0].blocking == "blocks"


def test_the_generated_proof_is_DERIVED_from_the_trunk_proof():
    """Not merely similar to it — generated from it, byte for byte apart from
    the rule path.

    The hand-written variant this replaced drifted immediately: it counted
    `"ruleId"` matches through `grep -c … || true` with stderr discarded, so an
    ast-grep that never ran returned 0 and the clean-tree check passed. Review
    found it downstream (mtg-cube-ai#2120). That is #2110's shape one level up —
    a fix landing on one of several copies — so there is now one copy.
    """
    trunk = pg.TRUNK_PROOF.read_text()
    generated = pg.proof_for("demo")
    # The behavioural core must survive the re-pathing.
    for anchor in ("seeded violation was NOT detected", "stayed red after",
                   "never named the seeded file", "status > 1"):
        assert anchor in generated, f"{anchor!r} lost in derivation"
        assert anchor in trunk, f"{anchor!r} not in the trunk proof — anchor is stale"
    # And the derivation must be a rewrite of the trunk, not a lookalike.
    assert len(generated.splitlines()) >= len(trunk.splitlines()) - 2


def test_a_trunk_proof_that_moved_is_a_hard_error():
    """If the rule-path block changes shape, the propagator must REFUSE rather
    than emit a proof it could not re-path. Silently shipping something weaker
    is the exact failure this derivation removes."""
    import pytest
    original = pg._TRUNK_RULE_BLOCK
    try:
        pg._TRUNK_RULE_BLOCK = "a block that is not in the file"
        with pytest.raises(SystemExit):
            pg.proof_for("demo")
    finally:
        pg._TRUNK_RULE_BLOCK = original


def test_the_generated_proof_fails_closed_when_the_scanner_does_not_run():
    """ast-grep exits 0 clean / 1 findings / >1 TOOL FAILURE (measured: 6 for a
    missing rule, 8 for a malformed one). Collapsing the third into "findings"
    makes a scanner that never ran read as a gate doing its job."""
    assert "status > 1" in pg.proof_for("demo")
    assert "establishes NOTHING" in pg.proof_for("demo")


def test_the_generated_proof_unsets_CDPATH():
    """`cd` ECHOES the resolved directory when CDPATH is set, so
    `$(cd ... && pwd)` returns the path TWICE separated by a newline and every
    path built from it is garbage. Omitting this produced `rule not found`
    against a file that plainly existed, in a real downstream repo.

    Environment state a script inherits is part of its input.
    """
    assert "unset CDPATH" in pg.proof_for("demo")


def test_the_generated_proof_checks_ALL_THREE_directions():
    """A proof that only seeds a violation cannot tell a working gate from one
    that flags everything — and one that only checks those two cannot tell a
    working gate from one that is stuck red. The trunk proof has three phases;
    the derivation must carry all of them, not just the two the hand-written
    variant had."""
    body = pg.proof_for("demo")
    assert "clean tree reported findings" in body      # 1. clean stays green
    assert "seeded violation was NOT detected" in body  # 2. dirty goes red
    assert "stayed red after the violation was removed" in body  # 3. and back
    # And it must name the file it found, or a red run is not actionable.
    assert "never named the seeded file" in body


def test_the_generated_proof_signs_off_under_ITS_OWN_rule_name():
    """The success line is what an operator reads. Propagated unrewritten, a
    proof for `demo` announces `raw-caught-to-logger` and reads as proof of a
    gate this repo does not have."""
    assert "ok: demo goes red" in pg.proof_for("demo")
    assert "raw-caught-to-logger goes red" not in pg.proof_for("demo")


# --- the baseline must not count the tool's OWN proof material ----------------


def _repo_with(tmp_path, *, real: int, seeded: int):
    """A target repo holding `real` genuine violations and `seeded` fixture ones."""
    body = ("export function h{n}() {{ try {{ a(); }} "
            "catch (e) {{ console.error('x', e); }} }}\n")
    src = tmp_path / "src" / "lib" / "server"
    src.mkdir(parents=True)
    (src / "code.ts").write_text("".join(body.format(n=i) for i in range(real)))
    fx = tmp_path / "rules" / "fixtures" / "raw-caught-to-logger" / "src" / "lib" / "server"
    fx.mkdir(parents=True)
    (fx / "violations.ts").write_text("".join(body.format(n=i) for i in range(seeded)))
    return tmp_path


def test_the_baseline_excludes_the_proof_material_this_tool_ships(tmp_path):
    """The fixture contains seeded violations BY DESIGN. Counting them as the
    target's backlog is a category error, and it is not hypothetical: the second
    propagation run reported mtg-cube-ai at 10 and companion-ai at 14 against
    directly-measured 0 and 4. Every extra finding was this tool's own fixture.

    The consequence is the part that matters. mtg-cube-ai's gate is `blocks`
    BECAUSE its baseline is zero; a baseline of 10 derives `advisory`. So a
    re-run would have silently DOWNGRADED a working gate on the strength of a
    mis-scoped measurement — inside the one function whose whole job is deciding
    that tier.
    """
    if shutil.which("ast-grep") is None:
        pytest.fail("ast-grep missing, so this measurement was never exercised")
    repo = _repo_with(tmp_path, real=2, seeded=5)
    got = pg.measure(repo, pg.TRUNK / "rules" / "raw-caught-to-logger.yml")
    assert got == 2, (
        f"expected the 2 real violations, got {got}. Anything higher means the "
        f"seeded proof material under rules/fixtures/ was counted as backlog."
    )


def test_the_exclusion_is_explicit_not_inherited_from_the_rule(tmp_path):
    """Anti-vacuous, and it pins WHY the glob is passed rather than trusted.

    The rule's own `ignores: fixtures/**` resolves relative to the RULE FILE's
    directory. Measuring with the trunk's rule points that at the trunk's
    fixtures, so the copy in the target repo is not excluded at all — which is
    exactly how the wrong number arrived. If someone deletes the explicit glob
    believing the rule already covers it, this goes red.
    """
    assert pg._PROOF_MATERIAL_GLOB == "!rules/fixtures/**"
    repo = _repo_with(tmp_path, real=0, seeded=4)
    assert pg.measure(repo, pg.TRUNK / "rules" / "raw-caught-to-logger.yml") == 0
