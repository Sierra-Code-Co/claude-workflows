"""Path containment at the two remaining untrusted-input boundaries (T005g/T005h).

Shapes DERIVED from the guard's own two-layer structure rather than recalled,
per FR-008a — recall is what produced the four decorative tests this suite's
mutation proof caught last week.

  layer                     sees                          blind to
  ------------------------  ----------------------------  ----------------------
  schema pattern / textual  '/abs', '../x', 'a/../x', ''  symlinks
  contained() / resolved    where the path actually lands  nothing here

So the file is organised around one question per layer plus the case that
separates them: a CLEAN relative path pointing at a symlink whose target is
outside the tree. That case is the only one that fails if the resolved-path
layer is deleted, which is what stops these tests from being satisfied by the
regex alone — the exact "passes for an unrelated reason" failure that made a
previous containment test in this repo survive the deletion of its own subject.

The anti-vacuous half matters as much: '..foo' and 'a/..b/c' are ordinary
filenames and MUST be accepted. A guard that greps for the substring '..'
passes every refusal test here while breaking real paths, and it would look
identical in the summary.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest
from review_plan_v2 import paths
from review_plan_v2.gates import registry
from review_plan_v2.gates.structural import StructuralAnalyzer
from review_plan_v2.types import FileChange

# --- layer 1: the textual check ----------------------------------------------

REFUSED_TEXTUALLY = [
    "/etc/passwd", "../x", "a/../../etc/passwd", "..", "", "/",
    # Both found by review of this module and CONFIRMED by measurement before
    # being fixed — neither was accepted on the reviewer's say-so.
    "a\n/../x",                # `.` crosses no line terminator, so the old
                               # traversal lookahead could not reach this `..`
    "..\\..\\windows",         # backslash is a SEPARATOR on Windows, so this
    "C:\\tmp\\evil.sh",        # holds no `..` segment when split on "/"
    "a\\b",
]
ACCEPTED_TEXTUALLY = ["tests/proofs/run-all.sh", "rules/x.yml", "a.sh", "..foo", "a/..b/c"]


@pytest.mark.parametrize("raw", REFUSED_TEXTUALLY)
def test_an_escaping_string_is_refused_before_the_filesystem_is_touched(raw):
    assert paths.is_safe_relative(raw) is False


@pytest.mark.parametrize("raw", ACCEPTED_TEXTUALLY)
def test_an_ordinary_relative_path_is_accepted(raw):
    """Anti-vacuous. '..foo' and 'a/..b/c' are filenames, not traversals.

    A guard matching the SUBSTRING '..' rather than the SEGMENT passes every
    refusal case above and breaks these, and nothing in a green summary would
    show the difference.
    """
    assert paths.is_safe_relative(raw) is True


# --- layer 2: the resolved-path check ----------------------------------------


@pytest.fixture()
def tree(tmp_path: pathlib.Path):
    """A repo, a file outside it, and a symlink from inside pointing out."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "real.sh").write_text("#!/bin/sh\nexit 1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.sh").write_text("#!/bin/sh\necho pwned\n")
    os.symlink(outside, root / "link")
    return root, outside


def test_a_symlink_pointing_outside_the_root_is_refused(tree):
    """THE case that proves the resolved layer is not decorative.

    'link/escape.sh' is a textually perfect relative path: no leading slash, no
    '..' segment. Every string-level check in this file accepts it. Only
    resolving the symlink shows it lands outside the tree.
    """
    root, _ = tree
    assert paths.is_safe_relative("link/escape.sh") is True, (
        "the premise of this test is that the textual layer accepts it"
    )
    assert paths.safe_join(root, "link/escape.sh") is None


def test_a_real_file_inside_the_root_is_accepted(tree):
    root, _ = tree
    assert paths.safe_join(root, "tests/real.sh") is not None


def test_a_path_that_does_not_exist_yet_is_still_judged_by_where_it_would_land(tree):
    """Containment must not depend on existence, or the check would be skipped
    for exactly the paths a typo'd or hostile registry supplies."""
    root, _ = tree
    assert paths.safe_join(root, "tests/not-created.sh") is not None
    assert paths.safe_join(root, "link/not-created.sh") is None


def test_the_root_itself_is_contained_but_its_parent_is_not(tree):
    root, _ = tree
    assert paths.contained(root, root) is True
    assert paths.contained(root.parent, root) is False


def test_an_absolute_path_is_refused_even_when_the_file_exists(tree):
    """`Path(root) / "/outside/escape.sh"` IS `/outside/escape.sh` — pathlib
    discards the left operand. Existence is what made this dangerous: the old
    `.is_file()` check passed, so the path was accepted and then executed."""
    root, outside = tree
    escape = str(outside / "escape.sh")
    assert pathlib.Path(escape).is_file(), "the fixture did not create the target"
    assert paths.safe_join(root, escape) is None


def test_an_unresolvable_path_is_not_contained(monkeypatch):
    """The 'cannot tell' branch, which had no test until review pointed it out.

    Forced rather than staged, because the natural triggers are
    platform-dependent: a permission error needs a non-root runner, and a
    symlink loop does NOT raise on 3.14 (it resolves lexically), which is itself
    why this module no longer claims loops return False.
    """
    def boom(self, *a, **k):
        raise OSError("forced")
    monkeypatch.setattr(pathlib.Path, "resolve", boom)
    assert paths.contained("anything", "/repo") is False


def test_an_embedded_nul_returns_None_rather_than_raising():
    """`safe_join` promises `Path | None`. `resolve()` raises ValueError — NOT
    OSError — on an embedded NUL, so the first draft broke its own contract on
    exactly the hostile input the function exists to handle."""
    assert paths.safe_join("/tmp", "a\x00b") is None


def test_a_symlink_loop_does_not_propagate(tmp_path):
    """Whatever the interpreter does with a loop, this must return a bool."""
    a, b = tmp_path / "a", tmp_path / "b"
    os.symlink(b, a)
    os.symlink(a, b)
    assert isinstance(paths.contained(a, tmp_path), bool)


# --- T005g: the registry -----------------------------------------------------


def _gate(**over):
    gate = {
        "id": "structural.demo",
        "tier": "deterministic",
        "blocking": "blocks",
        "order": 20,
        "cost": "free",
        "rule": "rules/demo.yml",
        "failure_proof": "tests/real.sh",
    }
    gate.update(over)
    return gate


@pytest.fixture()
def registry_tree(tree):
    """The `tree` fixture plus the rule file a structural gate must name."""
    root, outside = tree
    (root / "rules").mkdir()
    (root / "rules" / "demo.yml").write_text("id: demo\nlanguage: python\n")
    return root, outside


def test_a_valid_registry_still_loads(registry_tree):
    """Anti-vacuous control. Without it, a guard that refused EVERY path would
    pass every refusal test below and disable the whole portfolio."""
    root, _ = registry_tree
    reg = registry.load_registry({"version": 1, "gates": [_gate()]}, root)
    assert reg.gates[0].failure_proof == "tests/real.sh"


@pytest.mark.parametrize("field", ["failure_proof", "rule"])
@pytest.mark.parametrize("bad", ["/etc/passwd", "../../etc/passwd", "a/../../etc/passwd"])
def test_an_escaping_gate_path_is_refused_at_load(registry_tree, field, bad):
    """Both fields, because both are resolved and handed onward — and
    `failure_proof` is EXECUTED by SC-004, not merely read."""
    root, _ = registry_tree
    with pytest.raises(registry.RegistryError):
        registry.load_registry({"version": 1, "gates": [_gate(**{field: bad})]}, root)


@pytest.mark.parametrize("field", ["failure_proof", "rule"])
def test_a_symlinked_gate_path_is_refused_at_load(registry_tree, field):
    """The half the schema pattern cannot reach.

    Deleting `_check_paths_are_contained` leaves every other registry test in
    this file green; only this one goes red. That is the whole reason it exists.
    """
    root, _ = registry_tree
    with pytest.raises(registry.RegistryError, match="escapes the repository"):
        registry.load_registry(
            {"version": 1, "gates": [_gate(**{field: "link/escape.sh"})]}, root
        )


def test_an_absolute_failure_proof_that_EXISTS_is_still_refused(registry_tree):
    """The precise pre-T005g bug, not a near miss.

    `repo_root / "/outside/escape.sh"` is `/outside/escape.sh`, which is a real
    file, so `.is_file()` returned True and the gate loaded. FR-007 was
    satisfied by a proof living outside the repository, which SC-004 would then
    run.
    """
    root, outside = registry_tree
    escape = str(outside / "escape.sh")
    assert pathlib.Path(escape).is_file()
    with pytest.raises(registry.RegistryError):
        registry.load_registry({"version": 1, "gates": [_gate(failure_proof=escape)]}, root)


def test_the_refusal_names_the_gate_and_the_field(registry_tree):
    """A load failure that does not say which key is wrong sends the reader to
    the whole file — the rule `_validate_against_schema` already follows."""
    root, _ = registry_tree
    with pytest.raises(registry.RegistryError) as exc:
        registry.load_registry(
            {"version": 1, "gates": [_gate(failure_proof="link/escape.sh")]}, root
        )
    assert "structural.demo.failure_proof" in str(exc.value)


def test_a_gate_without_a_rule_is_unaffected(registry_tree):
    """`rule` is optional, and None must not be mistaken for an escaping path —
    the shape that turns a security check into an outage on valid input."""
    root, _ = registry_tree
    doc = {"version": 1, "gates": [_gate(id="reviewer.correctness", tier="probabilistic",
                                         blocking="advisory", cost="llm", order=100,
                                         rule=None)]}
    doc["gates"][0].pop("rule")
    assert registry.load_registry(doc, root).gates[0].rule is None


# --- the schema as a STANDALONE contract -------------------------------------
#
# Every test above passes with the schema's path pattern deleted, measured by
# mutation rather than assumed: `load_registry` runs the Python containment
# check on the same input, so through that entrypoint the pattern is redundant
# and the tests above cannot see it.
#
# It is not redundant, because the schema has consumers the loader does not:
# it ships in `specs/003-gate-portfolio/contracts/` as the published contract,
# and anything validating a `gates.yml` against it directly — an editor, a CI
# YAML check, another repo adopting the portfolio — gets the pattern and none
# of registry.py. So the schema is tested AS a schema, standalone, which is the
# only way the assertion means anything.


def _schema_errors(gate: dict) -> list[str]:
    """Validate against the shipped schema alone. No loader involved."""
    from jsonschema import Draft202012Validator

    schema = json.loads(registry.GATE_REGISTRY_SCHEMA.read_text())
    doc = {"version": 1, "gates": [gate]}
    return [
        "/".join(str(p) for p in e.absolute_path)
        for e in Draft202012Validator(schema).iter_errors(doc)
    ]


@pytest.mark.parametrize("field", ["failure_proof", "rule"])
@pytest.mark.parametrize("bad", REFUSED_TEXTUALLY)
def test_the_schema_alone_rejects_an_escaping_path(field, bad):
    assert f"gates/0/{field}" in _schema_errors(_gate(**{field: bad}))


@pytest.mark.parametrize("good", ACCEPTED_TEXTUALLY)
def test_the_schema_alone_accepts_an_ordinary_path(good):
    """Anti-vacuous, and the reason the pattern matches segments not substrings:
    a stricter pattern would reject '..foo' and break valid portfolios."""
    assert _schema_errors(_gate(failure_proof=good)) == []


def test_the_two_schema_copies_stay_byte_identical():
    """The package copy is what runs; the spec copy is what people read. A
    pattern added to one and not the other is a contract that lies."""
    shipped = registry.GATE_REGISTRY_SCHEMA.read_bytes()
    published = (
        pathlib.Path(__file__).resolve().parents[2]
        / "specs" / "003-gate-portfolio" / "contracts" / "gate-registry.schema.json"
    ).read_bytes()
    assert shipped == published


# --- T005h: the structural analyzer ------------------------------------------


def _fc(path: str) -> FileChange:
    return FileChange(path=path, is_binary=False, is_renamed_from=None,
                      added_lines=(), diff_text="", language="python")


def test_an_escaping_target_is_never_handed_to_ast_grep(tree):
    """`_files_for_globs` uses fnmatch, where `*` matches `/`, so no glob in
    this module bounds a target path. Nothing enforced containment before this."""
    root, _ = tree
    safe, refused = StructuralAnalyzer._partition_contained(
        [_fc("src/a.py"), _fc("/etc/passwd"), _fc("../../../etc/shadow"),
         _fc("link/escape.py")],
        str(root),
    )
    assert [f.path for f in safe] == ["src/a.py"]
    assert refused == ["/etc/passwd", "../../../etc/shadow", "link/escape.py"]


def test_a_refused_target_is_named_in_the_coverage_gaps(tree):
    """FR-011's rule applied here: named, never merely counted. A target dropped
    silently is a file NOBODY examined, rendered as a file that was clean."""
    root, _ = tree
    res = StructuralAnalyzer(rules_dir=root / "rules").run([_fc("/etc/passwd")], workdir=str(root))
    gaps = "\n".join(res.coverage_gaps())
    assert "/etc/passwd" in gaps
    assert "outside the working directory" in gaps


def test_a_refused_target_makes_coverage_incomplete(tree):
    """The dangerous direction, and the one an early return hides.

    Refused paths are removed before `coverable_file_count` is computed, so a
    run whose only coverable file was refused counts ZERO — the premise below —
    and looked exactly like a markdown-only PR with no completeness question to
    answer. There was a question; the gate declined to answer it.
    """
    root, _ = tree
    (root / "rules").mkdir()
    (root / "rules" / "demo.yml").write_text("id: demo\nlanguage: python\n")
    res = StructuralAnalyzer(rules_dir=root / "rules").run([_fc("/etc/passwd")], workdir=str(root))
    assert res.coverable_file_count == 0, "the premise: this run counts as empty"
    assert res.had_nothing_to_cover is False, (
        "a refused file read as 'nothing needed covering', which is how the "
        "skip reason was being swallowed downstream"
    )
    assert res.coverage_is_complete is False, (
        "a refused file was reported as complete coverage of nothing"
    )


def test_refusals_survive_the_early_returns(tree):
    """Both early exits construct their own StructuralResult, so each one is a
    separate chance to drop the refusal list. Checked on the no-rules exit."""
    root, _ = tree
    res = StructuralAnalyzer(rules_dir=root / "missing-rules").run(
        [_fc("/etc/passwd")], workdir=str(root)
    )
    assert res.skipped is True
    assert res.refused_paths == ["/etc/passwd"]
    assert any("/etc/passwd" in g for g in res.coverage_gaps())


def test_ordinary_targets_are_untouched(tree):
    """Anti-vacuous. A partition that refused everything would satisfy every
    test above while switching the gate off entirely."""
    root, _ = tree
    safe, refused = StructuralAnalyzer._partition_contained(
        [_fc("src/a.py"), _fc("src/..b/c.py"), _fc("deep/nested/path/d.py")], str(root),
    )
    assert len(safe) == 3 and refused == []


def test_a_refusal_and_a_skip_reason_are_reported_TOGETHER(tree):
    """Review-found gap: the skipped path builds `refused + [skip_reason]`, and
    nothing pinned that both survive. Reporting only the skip reason is how the
    refusal — the more specific fact — gets lost behind the general one."""
    root, _ = tree
    res = StructuralAnalyzer(rules_dir=root / "nope").run(
        [_fc("/etc/passwd")], workdir=str(root)
    )
    gaps = res.coverage_gaps()
    assert any("/etc/passwd" in g for g in gaps)
    assert any("no structural rules configured" in g for g in gaps)


# --- the other call sites still enforce it -----------------------------------
#
# Consolidating five copies onto one predicate means each call site's own
# enforcement is now a one-line call that could be deleted without touching
# `paths.py`. Review asked for exactly this and was right to: a shared helper
# with no call-site coverage is a guard that tests itself and nothing else.


def test_standing_context_refuses_an_unreadable_path_by_NAME(tmp_path, monkeypatch):
    """A deliberate behaviour change made during consolidation, now pinned.

    `gather` previously swallowed an OSError from `resolve()` with a bare
    `continue` — silent. Routing it through `contained` makes it report as
    refused instead. Silent-skip vs named-refusal is this spec's whole subject,
    so the new behaviour is the correct one, but it needed saying out loud.
    """
    from review_plan_v2.context import standing

    (tmp_path / "conventions.md").write_text("x")
    real_resolve = pathlib.Path.resolve

    def flaky(self, *a, **k):
        if self.name == "conventions.md":
            raise OSError("forced")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "resolve", flaky)
    _, report = standing.gather(tmp_path, ["conventions.md"])
    assert any("conventions.md" in r for r in report.refused)


def test_verify_input_resolution_refuses_a_symlinked_path(tmp_path):
    """`resolve_input`'s textual layer rejects '../x' and '/abs' before
    containment is ever consulted, so the `contained` call there had no shape
    that could reach it. A repo-internal symlink is that shape."""
    from review_plan_v2.verification.classify import Check
    from review_plan_v2.verification.verify import InputRejected, resolve_input

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.ts").write_text("export const x = 1\n")
    root = tmp_path / "repo"
    root.mkdir()
    os.symlink(outside, root / "link")

    with pytest.raises(InputRejected, match="escapes the checkout"):
        resolve_input(Check("enumerate", "link/secret.ts::x"), root)
