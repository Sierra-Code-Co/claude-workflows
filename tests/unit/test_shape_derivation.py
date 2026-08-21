"""The shape-derivation validator, tested against the two proofs that shipped broken (T034a).

FR-008a exists because of a specific, repeated failure: an author writes a gate,
then writes the proof by recalling what the gate handles. Recall reproduces the
set the gate already handles, so the proof confirms the implementation instead of
the requirement, and the shape nobody thought of is exactly the shape that ships
broken.

Both fixtures below are the REAL pre-fix artifacts, not invented ones:

  * the `raw-caught-to-logger` fixture before the catch-binding near-miss existed.
    Without it, a rule that also flags `modelId`, `idx` and `toolCallId` — every
    identifier that happens to sit inside a catch block — passes the entire proof.

  * the finding-envelope test set before the omitted-`claim` cases existed. It
    covered explicit `null` (the shape the author thought of) and not absence
    (the shape a model emits when it has nothing to say). With `claim` merely
    optional, a finding could carry `verdict: confirmed` and no claim at all and
    validate, defeating FR-002 entirely.

A validator that accepts either one is not a validator, so those two rejections
are the RED step. The anti-vacuous controls matter just as much: the CURRENT
artifacts must be ACCEPTED, or "rejects everything" would pass this file.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from derive_shapes import (
    RuleUnparseable,
    check_schema_field_absence,
    check_structural_rule,
    drop_rule_constraint,
    enumerate_rule_constraints,
    enumerate_schema_conditional_fields,
    load_waivers,
    scan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE = REPO_ROOT / "rules" / "raw-caught-to-logger.yml"
FIXTURE = REPO_ROOT / "rules" / "fixtures" / "raw-caught-to-logger"
SCHEMA_PATH = (
    REPO_ROOT / "scripts" / "review_plan_v2" / "gates" / "schemas"
    / "finding-envelope.schema.json"
)

# The near-miss that did not exist in the first version of the fixture. Deleting
# it reconstructs the pre-fix proof exactly.
#
# TUPLES, not single strings, and the reason is a lesson rather than a detail.
# These RED cases assert "a fixture with NO coverage for constraint X is
# rejected". Each was written when exactly one line supplied that coverage, so a
# single needle was enough. Adding the shadow-exclusion shapes gave both
# constraints a SECOND cover — N11 exercises the catch-binding unification and
# the catch_clause kind on its own — and deleting only the original line stopped
# reconstructing "no coverage". Both tests went green while asserting nothing.
#
# A deletion-based RED case is only as good as its list of what to delete, and
# that list silently goes stale every time the fixture grows. The needles must
# name every line that covers the constraint.
CATCH_BINDING_NEAR_MISS = ("catch (n6)", "const n11Outer")
ARROW_PARAMETER_NEAR_MISS = ("n9 =>", "n9b =>", "const n11Outer")


def _require_ast_grep() -> None:
    """Fail, never skip.

    Same rule as every other structural test here: a validator that silently
    does not run reports "no uncovered constraints", which is indistinguishable
    from full coverage. That is the defect this whole file exists to close.
    """
    if shutil.which("ast-grep") is None:
        pytest.fail(
            "ast-grep is not installed, so the shape-derivation validator was "
            "not exercised at all. Install it (brew install ast-grep) or see "
            ".github/workflows/tests.yml."
        )


@pytest.fixture()
def fixture_tree(tmp_path: Path) -> Path:
    """A writable copy of the real fixture tree.

    Copied out from under `rules/fixtures/` on purpose: the rule ignores
    `fixtures/**` relative to its own directory, so scanning it in place would
    report nothing and every assertion below would pass vacuously.
    """
    dest = tmp_path / "tree"
    shutil.copytree(FIXTURE, dest)
    return dest


def _delete_near_miss(root: Path, *needles: str) -> None:
    """Remove the fixture lines that carry a near-miss, reconstructing a pre-fix proof.

    Takes the binder text rather than a bare name because the two negatives being
    reconstructed here bind differently — N6 in a `catch (...)` clause, N9 as an
    arrow parameter — and that difference is the whole point of N9.
    """
    src = root / "src" / "lib" / "server" / "violations.ts"
    lines = src.read_text().splitlines()
    # EVERY needle must match something, not merely one of them. N9 is two lines
    # (an arrow binding and a promise .catch), and if either were renamed this
    # would silently reconstruct a DIFFERENT pre-fix state than the one the test
    # claims to be testing — while still passing, because the other line matched.
    missing = [n for n in needles if not any(n in ln for ln in lines)]
    assert not missing, f"no fixture line matches {missing}; the reconstruction is wrong"
    kept = [ln for ln in lines if not any(n in ln for n in needles)]
    assert len(kept) < len(lines), f"no fixture line matched any of {needles}"
    src.write_text("\n".join(kept) + "\n")


# --- RED 1: the pre-fix structural fixture must be rejected -------------------


def _waivers() -> dict[str, str]:
    return load_waivers(FIXTURE)


def test_the_pre_fix_fixture_is_rejected(fixture_tree: Path):
    """The proof that actually shipped, missing exactly one near-miss.

    Every other shape is present — 11 of them — so this fixture looks thorough.
    (Both lines covering the constraint are removed; see the needle tuples.)
    That is the point: thoroughness is not coverage, and only the mutation can
    tell them apart.
    """
    _require_ast_grep()
    _delete_near_miss(fixture_tree, *CATCH_BINDING_NEAR_MISS)

    result = check_structural_rule(RULE, fixture_tree, _waivers())

    assert not result.ok, (
        "the pre-fix fixture was ACCEPTED. It is missing the near-miss for the "
        "catch-binding unification, so a rule that flags every identifier inside "
        "a catch block passes it."
    )
    assert "rule.all[1].inside.has.pattern" in result.uncovered, (
        f"rejected, but not for the right reason. Expected the catch-binding "
        f"unification to be named as uncovered; got {result.uncovered}"
    )


def test_the_pre_validator_fixture_is_rejected(fixture_tree: Path):
    """The second RED case, and the one the validator itself found.

    Eleven recall-written shapes did not distinguish "the caught value" from
    "any single-argument arrow function's parameter", so `kind: catch_clause`
    could have been dropped in a refactor with the whole suite still green.
    Deleting N9 reconstructs that state.
    """
    _require_ast_grep()
    _delete_near_miss(fixture_tree, *ARROW_PARAMETER_NEAR_MISS)

    result = check_structural_rule(RULE, fixture_tree, _waivers())

    assert not result.ok, "the fixture without the arrow-function near-miss was ACCEPTED"
    assert "rule.all[1].inside.kind" in result.uncovered, result.uncovered


def test_the_rejection_names_the_uncovered_constraint(fixture_tree: Path):
    """A validator that says only "incomplete" sends the author back to recall —
    the very thing FR-008a removes. It has to name what to write."""
    _require_ast_grep()
    _delete_near_miss(fixture_tree, *CATCH_BINDING_NEAR_MISS)

    msg = check_structural_rule(RULE, fixture_tree, _waivers()).message()

    assert "raw-caught-to-logger" in msg
    assert "near-miss" in msg.lower()
    assert "rule.all[1].inside.has.pattern" in msg, (
        f"the uncovered constraint is not named in:\n{msg}"
    )


# --- the anti-vacuous control: the CURRENT fixture must be accepted -----------


def test_the_current_fixture_is_accepted(fixture_tree: Path):
    """Without this, "reject everything" passes the RED cases above.

    It also keeps the validator honest in the other direction: if it ever
    demands coverage for a constraint no fixture can exercise, this goes red
    rather than the demand quietly becoming folklore.
    """
    _require_ast_grep()
    result = check_structural_rule(RULE, fixture_tree, _waivers())
    assert result.ok, result.message()


# --- the harness must not misreport its own limits ----------------------------


@pytest.mark.parametrize("constraint", [
    "rule.all[0].inside.inside.has.regex",
    "rule.all[1].inside.has.pattern",
])
def test_the_two_load_bearing_constraints_are_mutable(constraint, fixture_tree):
    """The bug this test exists for shipped green and inverted the result.

    Deleting `regex` leaves `has: {field: function}`, from which ast-grep cannot
    derive a kind set — so the mutant was unparseable, and the constraint was
    classified "exempt: cannot be lost silently". That is the opposite of true.
    The console-callee regex and the `$ERR` unification are the two constraints
    the entire rule turns on, and a harness limitation was reporting itself as a
    property of the gate.

    They are weakened in place now (regex -> `.`, metavariable renamed) rather
    than deleted. If a future refactor reverts that, this goes red instead of the
    coverage number quietly dropping by two.
    """
    _require_ast_grep()
    rule = yaml.safe_load(RULE.read_text())
    mutated = drop_rule_constraint(rule, constraint)
    try:
        observed = scan(mutated, fixture_tree)
    except RuleUnparseable as exc:
        pytest.fail(
            f"{constraint} produced an unparseable mutant, so it would be "
            f"reported as exempt rather than proven: {exc}"
        )
    assert observed > scan(rule, fixture_tree), (
        f"weakening {constraint} did not loosen the rule, so the mutation is "
        f"not exercising it at all"
    )


def test_a_waiver_for_a_covered_constraint_is_an_error(fixture_tree: Path):
    """A stale exemption is worse than no exemption: it reads as considered."""
    _require_ast_grep()
    waivers = dict(_waivers())
    waivers["rule.all[1].inside.kind"] = "this one has a real near-miss (N9)"
    result = check_structural_rule(RULE, fixture_tree, waivers)
    assert not result.ok
    assert "rule.all[1].inside.kind" in result.stale_waivers
    assert "STALE" in result.message()


def test_a_waiver_for_a_constraint_that_no_longer_exists_is_an_error(fixture_tree: Path):
    """The rule moved and the waiver did not — the other way exemptions rot."""
    _require_ast_grep()
    waivers = dict(_waivers())
    waivers["rule.all[9].inside.kind"] = "constraint deleted in a refactor"
    result = check_structural_rule(RULE, fixture_tree, waivers)
    assert not result.ok
    assert "rule.all[9].inside.kind" in result.stale_waivers


def test_a_waiver_without_a_reason_is_rejected(tmp_path: Path):
    """A bare constraint name is recall again. The reason has to name the
    sibling that implies it, so the claim can be checked."""
    (tmp_path / "shape-waivers.yml").write_text("waivers:\n  rule.kind: ''\n")
    with pytest.raises(ValueError, match="reason"):
        load_waivers(tmp_path)


def test_the_repos_waivers_all_carry_a_reason():
    """Anti-vacuous control for the check above, against the real file."""
    waivers = _waivers()
    assert waivers, "the waiver file parsed to nothing"
    assert all(len(v.strip()) > 40 for v in waivers.values()), waivers


def test_the_constraint_enumeration_is_not_empty():
    """`all([])` is True. An enumeration bug turns the whole validator into a
    no-op that reports full coverage of nothing — the `had_nothing_to_cover`
    trap, one level up."""
    rule = yaml.safe_load(RULE.read_text())
    constraints = enumerate_rule_constraints(rule)
    assert len(constraints) >= 5, constraints


def test_constraints_are_derived_from_the_rule_not_from_a_declared_list():
    """The heart of FR-008a.

    Adding a constraint to the rule must raise the bar automatically. If the
    count came from anything the author writes by hand, the validator would
    inherit the recall problem it exists to remove.
    """
    rule = yaml.safe_load(RULE.read_text())
    before = len(enumerate_rule_constraints(rule))

    tightened = copy.deepcopy(rule)
    tightened["rule"]["all"].append({"inside": {"kind": "statement_block", "stopBy": "end"}})

    assert len(enumerate_rule_constraints(tightened)) > before


@pytest.mark.parametrize("constraint", enumerate_rule_constraints(
    yaml.safe_load(RULE.read_text())
))
def test_dropping_a_constraint_only_ever_loosens_or_narrows_scope(constraint, fixture_tree):
    """The mutation harness must relax the rule, never corrupt it.

    A mutant that reported findings the original did not — for a body
    constraint — would mean the mutation changed the rule's meaning rather than
    removing a restriction, and the coverage test above would be measuring the
    corruption. Scope includes go the other way by construction: removing one
    NARROWS the file set, so their control is a subset rather than a superset.
    """
    _require_ast_grep()
    rule = yaml.safe_load(RULE.read_text())
    mutated = drop_rule_constraint(rule, constraint)

    base = scan(rule, fixture_tree)
    try:
        mut = scan(mutated, fixture_tree)
    except RuleUnparseable:
        # A mutant ast-grep will not load is neither looser nor stricter; it is
        # no gate at all. The direction invariant does not apply — but the fact
        # must not vanish, so assert the classifier actually recorded it rather
        # than returning silently and leaving this branch unobserved.
        result = check_structural_rule(RULE, fixture_tree, _waivers())
        assert constraint in result.unmutable, (
            f"{constraint} produced an unparseable mutant but was not reported "
            f"as unmutable; it would silently vanish from the coverage account. "
            f"unmutable={result.unmutable}"
        )
        return

    # Anti-vacuous first: with an empty baseline, `mut <= base` holds trivially
    # for every scope mutation and the direction check asserts nothing. If the
    # fixture ever stops yielding findings, that must surface here rather than
    # be absorbed as silent agreement.
    assert base, (
        "the unmutated rule reported NOTHING on the fixture, so both direction "
        "assertions below are vacuous"
    )
    # POLARITY. "Dropping a constraint can only loosen" holds for a constraint
    # that RESTRICTS WHAT MATCHES. Two kinds here invert it, and both are real:
    #
    #   files[…]  — an include NARROWS the file set, so dropping one shrinks it.
    #   ….not.…   — a constraint under a negation restricts what is EXCLUDED, so
    #               dropping it excludes MORE and the rule reports FEWER.
    #
    # The `.not.` arm arrived with the shadow-exclusion clause, and this test
    # failed on it immediately — reporting ten findings "removed" by what is
    # genuinely a loosening mutation. That was the harness's assumption, not the
    # rule's behaviour. Worth stating plainly: an invariant that only holds for
    # positive constraints reads as universal right up until someone writes a
    # `not`, and then it accuses a correct rule.
    inverted = constraint.startswith("files[") or ".not." in constraint
    if inverted:
        assert mut <= base, f"dropping {constraint} ADDED findings: {mut - base}"
    else:
        assert base <= mut, f"dropping {constraint} REMOVED findings: {base - mut}"


# --- RED 2: the pre-fix schema test set must be rejected ----------------------


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _valid_envelope(**over) -> dict:
    doc = {
        "gate_id": "reviewer.correctness",
        "file": "a.ts",
        "severity": "major",
        "body": "b",
        "claim": None,
        "verdict": "unverifiable",
    }
    doc.update(over)
    return doc


def _without(doc: dict, key: str) -> dict:
    out = copy.deepcopy(doc)
    out.pop(key, None)
    return out


def test_the_pre_fix_envelope_test_set_is_rejected():
    """The test set as it stood: every VALUE case for the conditional fields,
    and no ABSENCE case for either.

    `if: {properties: {claim: {type: null}}}` succeeds VACUOUSLY when `claim` is
    absent — that is JSON Schema's rule, and it is why `required: [claim]` had to
    be added inside the `if`. A test set that never omits the field cannot tell
    the two spellings apart.
    """
    cases = [
        _valid_envelope(),
        _valid_envelope(claim=None, verdict="unverifiable"),
        _valid_envelope(verdict="refuted", verdict_detail="why"),
        _valid_envelope(verdict="unchecked"),
    ]

    result = check_schema_field_absence(_schema(), cases)

    assert not result.ok, (
        "the pre-fix envelope test set was ACCEPTED. It never omits `claim`, so "
        "the `claim: confirmed with no claim at all` bypass validates."
    )
    # BOTH conditional fields, not just the one the bypass was about. These
    # cases omit neither `claim` nor `verdict`, so a validator that reported
    # only `claim` would be half-blind and still pass a one-field assertion.
    assert set(result.uncovered) == {"claim", "verdict"}, result.uncovered


def test_the_current_envelope_test_set_is_accepted():
    """Anti-vacuous control. The absence cases exist now; they must pass."""
    cases = [
        _valid_envelope(),
        _valid_envelope(verdict="refuted", verdict_detail="why"),
        _without(_valid_envelope(verdict="confirmed"), "claim"),
        _without(_valid_envelope(), "verdict"),
    ]
    result = check_schema_field_absence(_schema(), cases)
    assert result.ok, result.message()


def test_every_field_named_in_a_conditional_is_enumerated():
    """Derived from the schema, so a new `if` raises the bar with no edit here."""
    fields = enumerate_schema_conditional_fields(_schema())
    assert set(fields) == {"claim", "verdict"}, fields


def test_a_new_conditional_raises_the_bar_automatically():
    """Enumeration is not the claim — REJECTION is.

    Asserting only that the new field is enumerated would pass even if
    check_schema_field_absence ignored the enumeration entirely, so the mutated
    schema is fed through the actual check with a case set that satisfies the
    old bar and not the new one.
    """
    schema = _schema()
    schema["allOf"].append({
        "if": {"properties": {"line": {"type": "null"}}, "required": ["line"]},
        "then": {"properties": {"severity": {"const": "info"}}},
    })
    assert "line" in enumerate_schema_conditional_fields(schema)

    # This set covers absence for claim and verdict — enough for the ORIGINAL
    # schema — but every case supplies `line`.
    cases = [
        _valid_envelope(line=1),
        _without(_valid_envelope(line=1), "claim"),
        _without(_valid_envelope(line=1), "verdict"),
    ]
    assert check_schema_field_absence(_schema(), cases).ok, (
        "control: this case set must satisfy the schema as it stands, or the "
        "rejection below would prove nothing about the NEW conditional"
    )
    result = check_schema_field_absence(schema, cases)
    assert not result.ok
    assert "line" in result.uncovered, result.uncovered


# --- the validator's own failure paths ----------------------------------------
#
# Flagged by the pre-push review as untested, and it was right: these are the
# branches that decide whether a malformed gate reports as broken or as clean,
# which is the one distinction this module cannot afford to get wrong.


def test_an_empty_constraint_enumeration_is_not_success():
    """`all([])` is True and every for-loop over [] completes.

    A parser bug that enumerated nothing would report full coverage of nothing —
    the `had_nothing_to_cover` trap, one level up from the gates it validates.
    """
    from derive_shapes import Coverage
    c = Coverage(artifact="stub", constraints=(), uncovered=())
    assert not c.ok
    assert "NO constraints were enumerated" in c.message()


def test_a_corrupted_mutation_is_not_reported_as_coverage():
    """If a mutation made the gate STRICTER, the coverage verdict derived from
    it is measuring the corruption, so it must not read as a pass."""
    from derive_shapes import Coverage
    c = Coverage(artifact="stub", constraints=("a",), uncovered=(), corrupted=("a",))
    assert not c.ok
    assert "STRICTER" in c.message()


def test_a_non_mapping_waiver_file_is_a_config_error_not_a_crash(tmp_path: Path):
    """`or {}` rescues only None. A list or scalar root reached .get() and died
    with AttributeError, which reads as a harness bug rather than a bad file."""
    (tmp_path / "shape-waivers.yml").write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="mapping at the top level"):
        load_waivers(tmp_path)


def test_a_missing_waiver_file_is_simply_no_waivers(tmp_path: Path):
    """Anti-vacuous control: rejection must not be the only outcome."""
    assert load_waivers(tmp_path) == {}


def test_a_broken_tool_is_distinguished_from_an_unparseable_mutant(monkeypatch, fixture_tree):
    """The discrimination the `unmutable` bucket depends on.

    If a genuinely broken ast-grep were classified as "mutant would not load",
    every constraint would land in `unmutable` and the run would report a clean,
    fully-exempt gate.
    """
    import subprocess as sp

    import derive_shapes

    class _Proc:
        returncode = 8
        stdout = ""
        stderr = "error: could not connect to language server"

    monkeypatch.setattr(derive_shapes.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(RuntimeError) as exc:
        derive_shapes.scan({"rule": {"kind": "identifier"}}, fixture_tree)
    assert not isinstance(exc.value, derive_shapes.RuleUnparseable)
    assert sp  # keep the import meaningful to linters


def test_a_hung_ast_grep_raises_rather_than_hanging_the_suite(monkeypatch, fixture_tree):
    """A mutant is a rule nobody wrote by hand, so pathological backtracking is
    live. A hung gate stops the very run that would have reported it."""
    import subprocess

    import derive_shapes

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ast-grep", timeout=120)

    monkeypatch.setattr(derive_shapes.subprocess, "run", _boom)
    with pytest.raises(RuntimeError, match="did not finish within"):
        derive_shapes.scan({"rule": {"kind": "identifier"}}, fixture_tree)


def test_a_match_outside_the_scan_root_is_named_not_crashed(monkeypatch, fixture_tree):
    """A bare `relative_to` raises ValueError, which surfaces as a harness crash.
    A path escaping the tree is a finding about the RULE and should say so."""
    import derive_shapes

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps([{
            "file": "/etc/passwd",
            "range": {"start": {"line": 0, "column": 0}},
        }])

    monkeypatch.setattr(derive_shapes.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(RuntimeError, match="outside the scan root"):
        derive_shapes.scan({"rule": {"kind": "identifier"}}, fixture_tree)


def test_two_matches_on_one_line_are_counted_separately(fixture_tree: Path):
    """The collapse the review caught.

    Keying on (file, line) alone means a mutation that adds a SECOND match to an
    already-matched line leaves the reported set unchanged — so a constraint the
    fixture DOES exercise is reported as uncovered.
    """
    _require_ast_grep()
    src = fixture_tree / "src" / "lib" / "server" / "twoup.ts"
    src.write_text(
        "try { a(); } catch (t1) { console.error('x:', t1); console.warn('y:', t1); }\n"
    )
    rule = yaml.safe_load(RULE.read_text())
    hits = [m for m in scan(rule, fixture_tree) if m[0].endswith("twoup.ts")]
    assert len(hits) == 2, f"two matches on one line collapsed into {len(hits)}: {hits}"


def test_an_empty_case_set_is_not_accepted_as_coverage():
    """The schema-side `all([])` trap, which this file documents for constraints
    and never checked for cases.

    `all(f in c for c in [])` is True, so an empty test set makes every field
    read as covered under the opposite phrasing. It happens to fall the safe way
    here — every field reports uncovered — but "happens to" is not a property,
    and a future refactor of that comprehension would flip it silently.
    """
    result = check_schema_field_absence(_schema(), [])
    assert not result.ok
    assert set(result.uncovered) == {"claim", "verdict"}, result.uncovered
