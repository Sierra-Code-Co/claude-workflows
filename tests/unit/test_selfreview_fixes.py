"""Regression guards for the defects found by reviewing this branch (2026-08-14).

Every case here is a shape the author's own derived list missed, and each was
surfaced by running review-plan-v2 against its own diff. Grouped in one file so
the provenance stays legible; they belong to four different modules.

The recurring pattern across all of them is worth naming: a check that verified
PRESENCE where the claim required SUBSTANCE.

  * `required` in JSON Schema     -> satisfied by an explicit null
  * `Path.exists()`               -> satisfied by a directory, and by ""
  * `case *"$want"*`              -> satisfied by a different version
  * `int(x or 0)`                 -> satisfied by a missing key
  * a comment asserting a rule    -> satisfied by nothing at all
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import jsonschema
import pytest
from review_plan_v2.aggregator import supersede_completeness_speculation
from review_plan_v2.gates.registry import Acceptance, RegistryError, load_registry
from review_plan_v2.types import Finding

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (REPO_ROOT / "scripts" / "review_plan_v2" / "gates" / "schemas"
     / "gate-registry.schema.json").read_text()
)


def _gate(**over):
    g = {
        "id": "structural.raw-caught-to-logger",
        "tier": "deterministic",
        "blocking": "blocks",
        "order": 20,
        "cost": "free",
        "failure_proof": "tests/proofs/run-all.sh",
        "rule": "rules/raw-caught-to-logger.yml",
    }
    g.update(over)
    return g


# --- the schema stated a biconditional and enforced one direction ------------


def test_probabilistic_gate_may_not_declare_itself_free():
    """The mirror image of the deterministic rule, unenforced until now.

    A probabilistic gate with `cost: free` sorts into the free band, so FR-012
    orders it ahead of every llm gate while it spends LLM money every run —
    defeating the ordering rule the schema comment claimed to keep checkable.
    """
    doc = {"version": 1, "gates": [_gate(id="p", tier="probabilistic", cost="free",
                                         blocking="advisory")]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


def test_deterministic_gate_may_not_declare_itself_llm():
    """The direction that WAS enforced — kept as the near-miss control, so a
    future edit cannot satisfy the test above by breaking this one."""
    doc = {"version": 1, "gates": [_gate(tier="deterministic", cost="llm")]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


def test_matching_tier_and_cost_still_validate():
    """Anti-vacuous control: both conditionals must still admit valid gates."""
    for tier, cost, blocking in (("deterministic", "free", "blocks"),
                                 ("probabilistic", "llm", "advisory")):
        doc = {"version": 1, "gates": [_gate(id=f"g.{tier}", tier=tier, cost=cost,
                                             blocking=blocking, order=10)]}
        jsonschema.validate(doc, SCHEMA)


# --- Path.exists() is a presence check, not a substance check ----------------


def test_empty_failure_proof_is_rejected():
    """`repo_root / ""` resolves to repo_root, which exists.

    So FR-007 — "a gate that cannot be shown to fail is not a gate" — was
    satisfied by naming no proof whatsoever.
    """
    doc = {"version": 1, "gates": [_gate(failure_proof="")]}
    with pytest.raises(RegistryError, match="failure_proof"):
        load_registry(doc, REPO_ROOT)


def test_directory_as_failure_proof_is_rejected(tmp_path):
    """`.exists()` is True for a directory; a directory is not a proof."""
    (tmp_path / "tests" / "proofs").mkdir(parents=True)
    (tmp_path / "not-a-file.sh").mkdir()
    doc = {"version": 1, "gates": [_gate(failure_proof="not-a-file.sh")]}
    with pytest.raises(RegistryError, match="failure_proof"):
        load_registry(doc, tmp_path)


def test_a_real_proof_file_still_loads():
    """Near-miss control for both cases above."""
    doc = {"version": 1, "gates": [_gate()]}
    assert load_registry(doc, REPO_ROOT).gates[0].failure_proof


# --- impossible states that JSON Schema cannot express -----------------------


def test_accepted_may_not_exceed_runs():
    """Draft 2020-12 bounds fields independently and cannot compare two of them,
    so `accepted: 50 / runs: 3` validated and yielded a 1667% acceptance rate —
    the number FR-014 promotes gates on."""
    with pytest.raises(RegistryError, match="exceeds runs"):
        Acceptance(runs=3, accepted=50, measured_through="2026-08-14")


def test_zero_runs_is_rejected():
    """Zero runs is division by zero in `rate`, and "measured over no runs" is
    not measurement."""
    with pytest.raises(RegistryError, match="runs"):
        Acceptance(runs=0, accepted=0, measured_through="2026-08-14")


def test_negative_accepted_is_rejected():
    with pytest.raises(RegistryError, match="accepted"):
        Acceptance(runs=5, accepted=-1, measured_through="2026-08-14")


def test_accepted_equal_to_runs_is_valid():
    """The boundary, and the near-miss control: 100% acceptance is legal."""
    assert Acceptance(runs=5, accepted=5, measured_through="2026-08-14").rate == 1.0


# --- a missing count is not a count of zero ----------------------------------


def _spec_finding():
    return Finding(
        file="a.ts", line=1, line_end=None, severity="actionable",
        category="correctness", sources=["correctness"],
        message="You may have missed other call sites elsewhere.",
    )


@pytest.mark.parametrize("coverage", [
    {"covered": True, "file_count": 10, "rule_ids": ["r"]},          # no finding_count
    {"covered": True, "finding_count": 30, "rule_ids": ["r"]},        # no file_count
])
def test_missing_counts_leave_the_hedge_alone(coverage):
    """Coercing an absent count to 0 prints "enumerated the whole checkout:
    0 site(s)" — a confident, specific, fabricated number — on top of a
    reviewer's correct hedge. Unknown must resolve to "do not supersede"."""
    out = supersede_completeness_speculation([_spec_finding()], coverage)
    assert out[0].severity == "actionable"
    assert "superseded" not in out[0].message


def test_present_counts_still_supersede():
    """Near-miss control: the fix must not disable the feature."""
    out = supersede_completeness_speculation(
        [_spec_finding()],
        {"covered": True, "finding_count": 0, "file_count": 0, "rule_ids": ["r"]},
    )
    assert out[0].severity == "info"


# --- the version pin, anchored on both sides ---------------------------------
#
# Driven through a real shell rather than reimplemented in Python: the thing
# under test is `case` glob semantics, and a Python port would test the port.


ASSERT_FN = r'''
assert_version() {
  name="$1"; want="$2"; got="$3"
  case "$got" in
    "$want") echo ok ;;
    "$want"[!0-9.]*) echo ok ;;
    *[!0-9.]"$want") echo ok ;;
    *[!0-9.]"$want"[!0-9.]*) echo ok ;;
    *) echo drift ;;
  esac
}
'''


def _assert_version(want: str, got: str) -> str:
    script = ASSERT_FN + f'assert_version tool "{want}" "{got}"\n'
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.mark.parametrize("want, got, why", [
    ("0.45.1", "ast-grep 0.45.10", "suffix digit — the bare-substring hole"),
    ("4.53.2", "14.53.2", "prefix digit — the right-anchored-only hole"),
    ("8.30.1", "8.30.10", "suffix digit"),
    ("1.7.12", "1.7.120", "suffix digit"),
    ("0.11.0", "version: 0.11.01", "suffix digit in multi-line output"),
    ("4.53.2", "v4.53.21", "both affixes"),
])
def test_near_miss_versions_are_drift(want, got, why):
    assert _assert_version(want, got) == "drift", why


@pytest.mark.parametrize("want, got", [
    ("0.45.1", "ast-grep 0.45.1"),
    ("4.53.2", "yq (https://github.com/mikefarah/yq/) version v4.53.2"),
    ("8.30.1", "8.30.1"),
    ("0.11.0", "ShellCheck - shell script analysis tool\nversion: 0.11.0\nlicense: GPL"),
    ("0.48.0", "0.48.0"),
    ("1.7.12", "1.7.12"),
])
def test_real_version_output_passes(want, got):
    """Without these the anchoring test is satisfied by a function that always
    reports drift, which would fail every build."""
    assert _assert_version(want, got) == "ok"


def _extract_case_block(rel: str, opener: str) -> str:
    """Pull the real `case ... esac` out of a shipped file, de-continued."""
    lines = (REPO_ROOT / rel).read_text().splitlines()
    out, capturing = [], False
    for ln in lines:
        stripped = ln.strip().rstrip("\\").strip()
        if stripped.startswith("#"):
            continue
        if opener in stripped:
            capturing = True
        if capturing:
            out.append(stripped)
        if capturing and stripped.startswith("esac"):
            break
    assert out, f"could not find `{opener}` in {rel}"
    assert out[-1].startswith("esac"), f"unterminated case block in {rel}"
    return "\n".join(out)


def _run_shipped_check(rel: str, opener: str, want: str, got: str, var: str) -> str:
    block = _extract_case_block(rel, opener)
    script = f'{var}="{want}"\nwant="{want}"\ngot="{got}"\ninstalled="{got}"\n{block}\n'
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return "drift" if proc.returncode != 0 or "DRIFT" in proc.stdout + proc.stderr else "ok"


@pytest.mark.parametrize("rel, opener, var", [
    ("Dockerfile", 'case "$got" in', "want"),
    (".github/workflows/tests.yml", 'case "$installed" in', "AST_GREP_VERSION"),
])
@pytest.mark.parametrize("want, got, expected", [
    ("0.45.1", "tool 0.45.10", "drift"),   # suffix digit
    ("4.53.2", "14.53.2", "drift"),        # prefix digit
    ("4.53.2", "v4.53.21", "drift"),       # both affixes
    ("0.45.1", "tool 0.45.1", "ok"),       # the real thing
    ("4.53.2", "version v4.53.2", "ok"),
])
def test_the_shipped_check_itself_rejects_near_misses(rel, opener, var, want, got, expected):
    """Executes the case block AS SHIPPED, rather than matching its text.

    The first version of this test looked for a substring and passed after a
    deliberately broken mutation, because removing one of four case arms left
    the substring intact — caught by its own RED step. A guard that reads the
    file cannot tell you the file behaves; running it can. Same reasoning that
    put a byte-identity guard on the packaged schemas rather than a "looks
    similar" check.
    """
    assert _run_shipped_check(rel, opener, want, got, var) == expected
