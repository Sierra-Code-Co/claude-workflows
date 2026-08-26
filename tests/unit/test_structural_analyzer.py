"""StructuralAnalyzer: absent coverage must never render as clean (T017/T018).

Shapes DERIVED from `run()`'s own branch structure, not recalled (FR-008a).
`run()` has six ways to produce an empty findings list, and exactly one of them
means "the repo is clean":

  branch                          findings   means
  ------------------------------  ---------  ---------------------------------
  ast-grep absent                 []         coverage ABSENT
  no rules configured             []         coverage ABSENT
  rule file unparseable           []         coverage ABSENT for that rule
  rule language unsupported       []         coverage ABSENT for that rule
  ast-grep exited 2+              []         coverage ABSENT for that rule
  ast-grep JSON unreadable        []         coverage ABSENT for that rule
  rule ran, matched nothing       []         CLEAN

Every row above gets a test, because they are indistinguishable downstream
unless the result carries its provenance. Three checks in this fleet shipped
without that distinction and were read as passing for months.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from review_plan_v2.gates.structural import (
    RuleOutcome,
    StructuralAnalyzer,
    StructuralResult,
)
from review_plan_v2.types import FileChange

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fc(path: str, binary: bool = False) -> FileChange:
    return FileChange(
        path=path, is_binary=binary, is_renamed_from=None,
        added_lines=(), diff_text="", language="ts",
    )


def _requires_ast_grep():
    if shutil.which("ast-grep") is None:
        pytest.fail(
            "ast-grep is not installed, so the structural analyzer was not "
            "exercised at all. A hard failure, not a skip — see "
            "tests/unit/test_structural_rules.py for the same reasoning."
        )


# --- absent coverage, branch by branch ---------------------------------------


def test_no_rules_configured_is_reported_not_silently_clean():
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "rules"
        empty.mkdir()
        res = StructuralAnalyzer(rules_dir=empty).run([_fc("src/lib/server/a.ts")], workdir=tmp)
    assert res.skipped
    assert not res.coverage_is_complete
    assert "no deterministic coverage" in res.skip_reason.lower() \
        or "no structural rules" in res.skip_reason.lower()


def test_no_rules_and_no_code_changed_is_NOT_reported():
    """The near-miss control for the test above, and the one that keeps the
    banner readable.

    Without it, every markdown-only PR in every repo that has not adopted rules
    yet prints an absent-coverage warning — and a warning that fires on every
    run is one nobody reads by the third week, which costs exactly the signal
    FR-004 is buying. The distinction is whether a completeness question could
    even have been posed, not whether rules happen to exist.
    """
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "rules"
        empty.mkdir()
        res = StructuralAnalyzer(rules_dir=empty).run([_fc("docs/README.md")], workdir=tmp)
    assert res.coverage_is_complete
    assert res.coverage_gaps() == []


def test_unknown_coverable_count_is_treated_as_a_gap():
    """`None` means "not determined". An undetermined coverage question must
    not resolve in favour of "covered" — that is the same defaulting error as
    `required` being read as a non-null guarantee."""
    res = StructuralResult(name="structural", coverable_file_count=None)
    assert not res.had_nothing_to_cover
    assert not res.coverage_is_complete


def test_missing_rules_directory_is_reported_not_silently_clean():
    with tempfile.TemporaryDirectory() as tmp:
        res = StructuralAnalyzer(rules_dir=Path(tmp) / "does-not-exist").run(
            [_fc("src/lib/server/a.ts")], workdir=tmp
        )
    assert res.skipped
    assert not res.coverage_is_complete


def test_unparseable_rule_file_is_a_gap_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        rules = Path(tmp) / "rules"
        rules.mkdir()
        (rules / "broken.yml").write_text("id: broken\n  bad: [indent\n")
        res = StructuralAnalyzer(rules_dir=rules).run([_fc("a.ts")], workdir=tmp)
    assert not res.skipped, "the analyzer itself ran; the RULE is what failed"
    assert not res.coverage_is_complete
    assert res.coverage_gaps(), "a broken rule must be named, not dropped"


def test_unsupported_language_is_a_gap_not_a_pass():
    """The near-miss for the parse test: valid YAML, unusable rule.

    Without this, `test_unparseable_rule_file_is_a_gap_not_a_pass` also passes
    against an implementation that only ever checks YAML syntax.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rules = Path(tmp) / "rules"
        rules.mkdir()
        (rules / "cobol.yml").write_text("id: cobol-rule\nlanguage: cobol\nrule:\n  kind: identifier\n")
        res = StructuralAnalyzer(rules_dir=rules).run([_fc("a.ts")], workdir=tmp)
    assert not res.coverage_is_complete
    assert any("cobol" in g for g in res.coverage_gaps())


def test_ast_grep_error_exit_is_a_gap_not_zero_matches():
    """rc 2+ must not be read as 'no matches'.

    Seeded with a syntactically valid YAML file that ast-grep itself rejects,
    so the failure comes from the real binary rather than a stubbed one.
    """
    _requires_ast_grep()
    with tempfile.TemporaryDirectory() as tmp:
        rules = Path(tmp) / "rules"
        rules.mkdir()
        # Valid YAML, valid language, but no `rule:` key — ast-grep errors.
        (rules / "norule.yml").write_text("id: norule\nlanguage: typescript\nseverity: error\nmessage: x\n")
        (Path(tmp) / "a.ts").write_text("const a = 1;\n")
        res = StructuralAnalyzer(rules_dir=rules).run([_fc("a.ts")], workdir=tmp)
    assert not res.coverage_is_complete, (
        "ast-grep failed to run this rule and the result claimed complete coverage"
    )
    assert res.coverage_gaps()


# --- the one branch that DOES mean clean -------------------------------------


def test_a_rule_that_ran_and_matched_nothing_is_complete_coverage():
    """The near-miss control for every test above.

    Without it, all of them are satisfied by an implementation that reports
    incomplete coverage unconditionally — which would be useless in the
    opposite direction.
    """
    _requires_ast_grep()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "lib" / "server"
        src.mkdir(parents=True)
        (src / "clean.ts").write_text(
            "try { a(); } catch (e) { console.error('x:', describeThrown(e).errMessage); }\n"
        )
        res = StructuralAnalyzer(rules_dir=REPO_ROOT / "rules").run(
            [_fc("src/lib/server/clean.ts")], workdir=tmp
        )
    assert not res.skipped
    assert res.findings == []
    assert res.coverage_is_complete
    assert res.coverage_gaps() == []


def test_a_rule_that_ran_and_matched_reports_the_finding():
    _requires_ast_grep()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "lib" / "server"
        src.mkdir(parents=True)
        (src / "dirty.ts").write_text(
            "try { a(); } catch (e) {\n  console.error(\n    'x:',\n    e,\n  );\n}\n"
        )
        res = StructuralAnalyzer(rules_dir=REPO_ROOT / "rules").run(
            [_fc("src/lib/server/dirty.ts")], workdir=tmp
        )
    assert res.coverage_is_complete
    assert len(res.findings) == 1
    f = res.findings[0]
    assert "raw-caught-to-logger" in f.message
    assert f.severity == "actionable"
    # 1-indexed like every other analyzer in this package; ast-grep is 0-indexed.
    assert f.line == 4, f"expected the `e,` line (4), got {f.line}"


def test_no_applicable_files_is_complete_coverage_not_a_gap():
    """A rule with nothing to scan RAN; it did not fail.

    Conflating the two would make every markdown-only PR report absent
    structural coverage, and a warning that fires on every run is one nobody
    reads by the third week.
    """
    _requires_ast_grep()
    with tempfile.TemporaryDirectory() as tmp:
        res = StructuralAnalyzer(rules_dir=REPO_ROOT / "rules").run(
            [_fc("README.md")], workdir=tmp
        )
    assert res.coverage_is_complete
    assert res.findings == []


def test_binary_files_are_never_handed_to_the_enumerator():
    _requires_ast_grep()
    with tempfile.TemporaryDirectory() as tmp:
        res = StructuralAnalyzer(rules_dir=REPO_ROOT / "rules").run(
            [_fc("src/lib/server/blob.ts", binary=True)], workdir=tmp
        )
    assert res.coverage_is_complete
    assert res.findings == []


# --- the `all([])` trap ------------------------------------------------------


def test_empty_rule_list_is_not_complete_coverage():
    """`all([])` is True. Without the explicit non-empty check, a result with
    zero rules reports COMPLETE coverage of nothing — the same shape as the
    `promoted_at: null` bypass, where a predicate was true for a reason its
    author never intended."""
    assert not StructuralResult(name="structural").coverage_is_complete


def test_one_failed_rule_among_many_still_breaks_coverage():
    res = StructuralResult(
        name="structural",
        rules=[
            RuleOutcome("ok-1", "a.yml", ran=True, match_count=0),
            RuleOutcome("ok-2", "b.yml", ran=True, match_count=3),
            RuleOutcome("broken", "c.yml", ran=False, error="exited 2"),
        ],
    )
    assert not res.coverage_is_complete
    assert res.coverage_gaps() == ["broken: exited 2"]


def test_all_rules_ran_is_complete_coverage():
    res = StructuralResult(
        name="structural",
        rules=[RuleOutcome("ok-1", "a.yml", ran=True), RuleOutcome("ok-2", "b.yml", ran=True)],
    )
    assert res.coverage_is_complete
    assert res.coverage_gaps() == []
