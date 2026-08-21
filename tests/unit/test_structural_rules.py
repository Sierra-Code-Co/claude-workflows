"""Per-shape fixture tests for the shared ast-grep rules (T016).

WHY SET EQUALITY AND NOT "every positive is found":
A rule that matched every identifier in the file would satisfy "each positive
shape is found" perfectly. The assertion here is that the reported line set
EQUALS the marked line set, so an over-match fails exactly as loudly as a miss.

WHY THE FIXTURE IS A DIRECTORY TREE:
`files:` and `ignores:` are part of the rule's policy — they decide what it
claims — and neither can be exercised from a single file. That is not a
theoretical gap: the previous fixture lived at
`specs/003-gate-portfolio/rules/fixture.ts`, a path matching NEITHER scope
glob, so `ast-grep scan --rule <rule> <fixture>` reported zero findings and
exited 0. The rule was fine; its proof was inert, and the documented
"check your rule works" command in rules/README.md printed nothing and
returned success. Measured 2026-08-14, before the rule was moved here.

WHY THE TREE IS COPIED TO A TEMP DIR BEFORE SCANNING:
The fixture holds real violations under a `src/lib/server/` path, so a repo-wide
scan would report the proof material as findings. The rule therefore ignores
`**/fixtures/**` — and copying the tree out from under that path is what keeps
the exclusion from also hiding the fixture from its own test.

WHY THERE IS NOW A TEST FOR THE EXCLUSION ITSELF:
Because the exclusion did not work. `ignores:` globs resolve relative to the
RULE FILE'S DIRECTORY, not to the scan root, so the `**/rules/fixtures/**` form
shipped in #30 matched nothing: a full-repo scan reported all 9 seeded
violations as real findings. Nothing caught it, because nothing in the suite
scanned this repo with its own rule. Third scope-key surprise on this one rule —
first `files:` filtering explicit path arguments, then the fixture living
outside its own rule's scope, now this. Scope keys get tests.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "rules"
FIXTURES_DIR = RULES_DIR / "fixtures"

# A line is expected to be reported iff it ENDS with exactly this token. Prose
# elsewhere in the fixtures mentions the marker by name; requiring it in
# trailing-comment position keeps documentation from silently becoming
# assertions.
MARKER = "// sg-expect"


def _require_ast_grep() -> str:
    """Fail, never skip.

    A skipped structural test is a completeness gate that reports nothing and
    exits 0 — the precise failure this portfolio exists to close (Principle I).
    CI installs ast-grep at the pinned version; if it is missing, that is a
    broken environment and the suite must say so.
    """
    path = shutil.which("ast-grep")
    if path is None:
        pytest.fail(
            "ast-grep is not installed, so the structural rules were not "
            "checked at all. This is a hard failure and not a skip: a "
            "completeness gate that silently does not run reports clean. "
            "Install it (brew install ast-grep) or see .github/workflows/tests.yml."
        )
    return path


def _rule_ids() -> list[str]:
    return sorted(p.stem for p in RULES_DIR.glob("*.yml"))


def _scan(rule: Path, target: Path) -> list[dict]:
    proc = subprocess.run(
        ["ast-grep", "scan", "--rule", str(rule), "--json", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise AssertionError(f"ast-grep failed ({proc.returncode}): {proc.stderr}")
    out = proc.stdout.strip()
    return json.loads(out) if out else []


def _marked_lines(root: Path) -> set[tuple[str, int]]:
    marked: set[tuple[str, int]] = set()
    for path in sorted(root.rglob("*.ts")):
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            if line.rstrip().endswith(MARKER):
                marked.add((path.relative_to(root).as_posix(), n))
    return marked


def _reported_lines(rule: Path, root: Path) -> set[tuple[str, int]]:
    return {
        (Path(m["file"]).resolve().relative_to(root.resolve()).as_posix(),
         m["range"]["start"]["line"] + 1)
        for m in _scan(rule, root)
    }


def _copy_fixture(rule_id: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES_DIR / rule_id, dest, dirs_exist_ok=True)
    return dest


# --- every rule is proven ----------------------------------------------------


def test_at_least_one_rule_exists():
    """Anti-vacuous guard for every parametrised test below.

    With zero rules the parametrisation is empty and the whole module reports
    green while asserting nothing.
    """
    assert _rule_ids(), f"no rules found in {RULES_DIR}"


@pytest.mark.parametrize("rule_id", _rule_ids())
def test_every_rule_has_a_fixture_tree(rule_id):
    root = FIXTURES_DIR / rule_id
    assert root.is_dir(), (
        f"rule {rule_id} has no fixture at {root}. A rule with no fixture has "
        f"no proof it matches what it claims (FR-007)."
    )
    assert list(root.rglob("*.ts")), f"fixture tree {root} contains no sources"


# --- the shape assertions ----------------------------------------------------


@pytest.mark.parametrize("rule_id", _rule_ids())
def test_fixture_marks_at_least_one_expected_match(rule_id):
    """Without this, a fixture whose markers were lost expects {} and passes
    against a rule that matches nothing — vacuously green in both halves."""
    marked = _marked_lines(FIXTURES_DIR / rule_id)
    assert marked, f"fixture for {rule_id} marks no expected matches"


@pytest.mark.parametrize("rule_id", _rule_ids())
def test_rule_reports_exactly_the_marked_lines(rule_id):
    _require_ast_grep()
    rule = RULES_DIR / f"{rule_id}.yml"
    with tempfile.TemporaryDirectory() as tmp:
        root = _copy_fixture(rule_id, Path(tmp) / "tree")
        expected = _marked_lines(root)
        actual = _reported_lines(rule, root)
    missed = sorted(expected - actual)
    extra = sorted(actual - expected)
    assert not missed, f"{rule_id} MISSED marked shapes: {missed}"
    assert not extra, f"{rule_id} OVER-MATCHED unmarked lines: {extra}"


# --- scope is policy: prove the exclusions are load-bearing -------------------
#
# "No findings in this file" is satisfied by a rule that finds nothing anywhere.
# Each scope negative therefore gets its near-miss control: the SAME BYTES at an
# in-scope path must be reported. That is what separates "the exclusion worked"
# from "the scan was inert".


@pytest.mark.parametrize(
    "excluded_rel, why",
    [
        ("src/lib/server/excluded.test.ts", "ignores: **/*.test.ts"),
        ("src/lib/components/out-of-scope.ts", "files: neither scope glob"),
    ],
)
def test_scope_negative_is_excluded_by_scope_and_not_by_inertness(excluded_rel, why):
    _require_ast_grep()
    rule_id = "raw-caught-to-logger"
    rule = RULES_DIR / f"{rule_id}.yml"
    source = (FIXTURES_DIR / rule_id / excluded_rel).read_text()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "tree"
        _copy_fixture(rule_id, root)
        reported = _reported_lines(rule, root)
        assert not [f for f, _ in reported if f == excluded_rel], (
            f"{excluded_rel} was reported despite {why}"
        )

        # The control: identical bytes, in-scope path.
        control = root / "src" / "lib" / "server" / "scope_control.ts"
        control.write_text(source)
        control_hits = [
            ln for f, ln in _reported_lines(rule, root)
            if f == "src/lib/server/scope_control.ts"
        ]
        assert control_hits, (
            f"the same bytes were NOT reported at an in-scope path either, so "
            f"'{excluded_rel} is excluded' proves nothing about {why} — the "
            f"scan is inert. This is the exact failure mode that made the "
            f"previous single-file fixture pass while finding zero shapes."
        )


# --- the exclusion must actually exclude -------------------------------------


def _scan_repo(rule: Path) -> list[str]:
    """Run one rule over the whole checkout, as a real review would."""
    proc = subprocess.run(
        ["ast-grep", "scan", "--rule", str(rule), "--json", "--", str(REPO_ROOT)],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )
    assert proc.returncode in (0, 1), proc.stderr[:400]
    return [m["file"] for m in json.loads(proc.stdout or "[]")]


@pytest.mark.parametrize("rule_id", _rule_ids())
def test_scope_keys_actually_exclude_proof_material(rule_id):
    """A full-repo scan must report nothing. This repo IS clean, and every
    fixture violation in it is deliberate.

    Absent this test the shipped `ignores:` glob matched nothing for a full
    release cycle, and the only symptom was 9 phantom findings on any real scan
    — which reads as "the rule works" to anyone not counting.
    """
    _require_ast_grep()
    hits = _scan_repo(RULES_DIR / f"{rule_id}.yml")
    assert hits == [], f"{rule_id} reported proof material as findings: {sorted(set(hits))}"


@pytest.mark.parametrize("rule_id", _rule_ids())
def test_the_exclusion_is_what_makes_the_repo_scan_clean(rule_id):
    """Mutation control for the test above.

    "Zero findings" is also what a rule that matches nothing produces, and this
    fleet has shipped that exact confusion twice. Dropping `ignores:` must make
    the same scan go non-zero — otherwise the clean result above is evidence of
    an inert rule rather than a working exclusion.
    """
    _require_ast_grep()
    import yaml
    doc = yaml.safe_load((RULES_DIR / f"{rule_id}.yml").read_text())
    if not doc.get("ignores"):
        pytest.skip(f"{rule_id} declares no ignores, so there is nothing to mutate")
    doc.pop("ignores")
    with tempfile.TemporaryDirectory() as td:
        mutated = Path(td) / f"{rule_id}.yml"
        mutated.write_text(yaml.safe_dump(doc))
        # The rule file moves, and `files:`/`ignores:` are rule-relative — so
        # this mutant is checked for "reports MORE than the real rule", not for
        # any absolute count.
        hits = _scan_repo(mutated)
    assert hits, (
        f"removing `ignores:` from {rule_id} changed nothing, so the clean "
        "full-repo scan proves the exclusion works only if the rule matches "
        "something in the first place — and it does not."
    )


def test_the_exclusion_does_not_over_match_consumer_fixture_directories():
    """The near-miss the clean-repo test could not see.

    `test_scope_keys_actually_exclude_proof_material` passes under BOTH wrong
    patterns this rule has shipped, because both leave this repo's own scan
    empty. Only an over-match negative separates them: a genuine violation in a
    directory named `fixtures` inside CONSUMER application code must still be
    reported.

    `**/fixtures/**` suppressed it — a scan false negative in a rule about
    unlogged errors, shipped fleet-wide, which is strictly worse than the
    proof-material noise it was fixing. Found by review-plan-v2 on this branch,
    hours after the opposite error (`**/rules/fixtures/**`, which excluded
    nothing) was fixed. The two mistakes point in opposite directions, so the
    test suite needs a negative in each.
    """
    _require_ast_grep()
    rule = RULES_DIR / "raw-caught-to-logger.yml"
    violation = "try { risky(); } catch (e) { console.error(e); }\n"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "consumer"
        for rel in ("src/lib/server/fixtures/seed.ts", "src/lib/server/real.ts"):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(violation)
        reported = {f for f, _ in _reported_lines(rule, root)}

    assert "src/lib/server/real.ts" in reported, (
        "the rule matched nothing at all, so this test proves nothing about "
        "over-matching — check the fixture shape before trusting the assertion"
    )
    assert "src/lib/server/fixtures/seed.ts" in reported, (
        "a real violation inside a consumer `fixtures/` directory was suppressed. "
        "The exclusion must be rule-relative (`fixtures/**`), not a wildcard "
        "(`**/fixtures/**`) that swallows every fixtures directory in every repo "
        "this rule is shipped to."
    )
