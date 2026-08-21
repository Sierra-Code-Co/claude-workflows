"""The verification stage as wired into the aggregator and renderer (T029/T030).

`test_verify.py` covers what a verdict IS. This covers what a verdict DOES —
whether the finding leaves the output, whether the drop is counted, whether the
marker renders. Those are separate claims, and the gap between them is where
silent degradation lives: a component whose logic is right and whose output
never moves.
"""
from __future__ import annotations

import pathlib

import pytest

from review_plan_v2.aggregator import aggregate, verify_findings
from review_plan_v2.output_format import drop_refuted, render_plain
from review_plan_v2.types import Finding

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "gold_set_corpus"

FALSE_CLAIM = {
    "kind": "return_shape", "subject": "describeThrown", "expected": "name, message",
    "check": {"method": "typecheck",
              "input": "web/src/lib/server/describe-thrown.ts::describeThrown"},
}
TRUE_CLAIM = {
    "kind": "symbol_exists", "subject": "stripBlockComments", "expected": "present",
    "check": {"method": "enumerate", "input": "src:stripBlockComments"},
}


def _f(msg, claim=None, line=18, file="web/src/lib/server/describe-thrown.ts",
       category="correctness", severity="actionable"):
    return Finding(file=file, line=line, line_end=None, severity=severity,
                   category=category, message=msg, sources=["correctness"], claim=claim)


# --- the merge defect this stage introduced ----------------------------------


def test_a_judgment_finding_is_not_merged_into_a_checkable_one():
    """Regression guard for a defect found by tests/proofs/verification_stage.sh.

    A claim:null finding on line 19 was inside the dedup window of a
    false-claim finding on line 18, so it merged; the claim was then refuted and
    BOTH disappeared. Dedup was already lossy here — it keeps one message — but
    verification turned lossy into silently destructive, deleting a finding that
    never asserted anything checkable.
    """
    merged = aggregate([[_f("checkable thing", FALSE_CLAIM, line=18),
                         _f("judgment thing", None, line=19)]])
    assert len(merged) == 2, [m.message for m in merged]


def test_two_checkable_findings_on_the_same_lines_still_merge():
    """Anti-vacuous control: the fix must not disable dedup. Without this, the
    guard above is satisfied by never merging anything."""
    a = _f("a", FALSE_CLAIM, line=18)
    b = _f("b", TRUE_CLAIM, line=19)
    b.sources = ["security"]  # distinct source, so the merge is observable
    merged = aggregate([[a, b]])
    assert len(merged) == 1
    assert merged[0].confidence == "high-confidence"
    assert merged[0].sources == ["correctness", "security"]


def test_two_judgment_findings_still_merge():
    merged = aggregate([[_f("a", None, line=18), _f("b", None, line=19)]])
    assert len(merged) == 1


def test_a_merged_finding_keeps_the_claim_belonging_to_its_own_text():
    """A merged finding renders `into.message`. If it carried `src`'s claim, the
    tool would verify one finding's assertion and print another's words."""
    merged = aggregate([[_f("first", FALSE_CLAIM, line=18), _f("second", TRUE_CLAIM, line=19)]])
    assert merged[0].message == "first"
    assert merged[0].claim == FALSE_CLAIM


# --- drop + count ------------------------------------------------------------


def test_drop_refuted_splits_and_counts():
    kept_in = _f("kept")
    kept_in.verdict = "confirmed"
    gone = _f("gone")
    gone.verdict = "refuted"
    unchecked = _f("unchecked")
    unchecked.verdict = "unchecked"
    kept, refuted = drop_refuted([kept_in, gone, unchecked])
    assert [f.message for f in kept] == ["kept", "unchecked"]
    assert [f.message for f in refuted] == ["gone"]


def test_the_stage_removes_the_refuted_finding_from_the_exit_code_path():
    """Dropping only at render time would print nothing and still exit 1.

    A review that reports clean and fails the build is its own silent failure —
    the operator trusts the printed output and cannot see why CI is red.
    """
    refuted: list[Finding] = []
    kept = aggregate([[_f("false claim", FALSE_CLAIM)]], repo_root=CORPUS,
                     refuted_out=refuted, verify_log=lambda m: None)
    from review_plan_v2.output_format import exit_code_for
    assert kept == []
    assert len(refuted) == 1
    assert exit_code_for(kept) == 0


def test_a_silent_drop_is_impossible_because_the_count_is_rendered():
    out = render_plain([], {"refuted_dropped": 2})
    assert "[VERIFIED-OUT] 2 finding(s)" in out
    assert "--no-verify" in out


def test_zero_refutations_prints_no_receipt():
    """The receipt is a signal, not decoration. Printing it at 0 would train the
    reader past it."""
    assert "[VERIFIED-OUT]" not in render_plain([], {"refuted_dropped": 0})


# --- markers -----------------------------------------------------------------


@pytest.mark.parametrize("verdict, expect", [
    ("confirmed", "[verified:"),
    ("unverifiable", "[UNVERIFIED:"),
    ("unchecked", "[UNCHECKED:"),
])
def test_verdicts_render_with_their_marker_and_evidence(verdict, expect):
    f = _f("something")
    f.verdict, f.verdict_detail = verdict, "declares ThrownDescription"
    out = render_plain([f])
    assert expect in out
    assert "declares ThrownDescription" in out


def test_an_unrun_stage_adds_no_marker():
    """verdict=None means the stage did not run. Annotating every finding on
    such a run would train the reader to ignore the marker, and the absence of
    the stage belongs in run health, not on each line."""
    out = render_plain([_f("something")])
    assert "[verified" not in out and "[UNVERIFIED" not in out and "[UNCHECKED" not in out


def test_a_marker_never_breaks_the_one_line_grep_contract():
    """FR-013: downstream `grep '^\\[ACTIONABLE\\]'` must keep working."""
    f = _f("something")
    f.verdict, f.verdict_detail = "unchecked", "line one\nline two"
    body = render_plain([f]).strip()
    assert len(body.splitlines()) == 1, body


def test_a_long_detail_is_truncated_not_dropped():
    f = _f("something")
    f.verdict, f.verdict_detail = "confirmed", "x" * 500
    out = render_plain([f])
    assert "…" in out
    assert len(out.splitlines()[0]) < 400


# --- the stage is off by default ---------------------------------------------


def test_no_repo_root_leaves_every_verdict_none():
    """`repo_root=None` is the honest encoding of "the stage did not run", and
    must render exactly as it did before US2."""
    out = aggregate([[_f("a", FALSE_CLAIM), _f("b", None)]])
    assert all(f.verdict is None for f in out)


def test_a_malformed_claim_is_unchecked_not_dropped_and_not_confirmed():
    logs: list[str] = []
    f = _f("a", claim="this is not an object")
    verify_findings([f], CORPUS, log=logs.append)
    assert f.verdict == "unchecked"
    assert any("malformed claim" in line for line in logs), logs


# --- gaps the review was right about ------------------------------------------


@pytest.mark.parametrize("raw, expect", [
    ({"file": "a.ts", "message": "m"}, None),                       # key absent
    ({"file": "a.ts", "message": "m", "claim": None}, None),        # explicit null
    ({"file": "a.ts", "message": "m", "claim": {"kind": "count"}}, {"kind": "count"}),
    ({"file": "a.ts", "message": "m", "claim": "not an object"}, "not an object"),
])
def test_parse_findings_forwards_the_claim_uncoerced(raw, expect):
    """Absent and explicit-null must both mean "no claim", and a malformed claim
    must survive the parser so the verifier can mark it `unchecked` with a log
    line. Sanitising here would move a security decision into the parser and
    silently discard evidence that a reviewer is emitting garbage."""
    import json as _json

    from review_plan_v2.reviewers.base import parse_findings
    out = parse_findings(_json.dumps([raw]), source="correctness", default_file="a.ts")
    assert len(out) == 1
    assert out[0].claim == expect


def test_no_verify_flag_reaches_the_config():
    """`merge_cli_into_config` reads `args.no_verify` through getattr, so a caller
    built before the flag existed must not crash — and a caller that passes it
    must actually turn the stage off."""
    import argparse

    from review_plan_v2.types import RunConfig, merge_cli_into_config

    def args(**over):
        base = dict(base=None, type="all", config=None, plain=True, agent=False,
                    no_color=False, force_full=False, no_static_analyzers=False,
                    no_cascade=False, dry_run=False, strict_config=False,
                    auto_pause_n=None, max_concurrency=None, dedup_window=None,
                    max_cost_usd=None)
        base.update(over)
        return argparse.Namespace(**base)

    assert merge_cli_into_config(args(), RunConfig()).no_verify is False
    assert merge_cli_into_config(args(no_verify=True), RunConfig()).no_verify is True
    # A config-file true must not be clobbered by argparse's False default.
    assert merge_cli_into_config(args(), RunConfig(no_verify=True)).no_verify is True


def test_the_verified_out_receipt_count_comes_from_the_real_pipeline():
    """The render test manufactures `{"refuted_dropped": 2}`; this drives the
    number from an actual aggregate() run, so the wiring that turns
    `refuted_out` into the summary field cannot silently revert to 0."""
    refuted: list[Finding] = []
    aggregate([[_f("false claim", FALSE_CLAIM), _f("judgment", None, line=40)]],
              repo_root=CORPUS, refuted_out=refuted, verify_log=lambda m: None)
    out = render_plain([], {"refuted_dropped": len(refuted)})
    assert "[VERIFIED-OUT] 1 finding(s)" in out, out


@pytest.mark.parametrize("payload, why", [
    # INTERIOR, not leading: the old code's .strip() ate a leading CR, so a
    # leading-CR case passed against the unfixed code and proved nothing.
    ("real detail\r[ACTIONABLE] fake.ts:1 [security] injected", "CR rewrites the line"),
    ("\x1b[2J\x1b[H owned", "ESC opens cursor/colour/title control sequences"),
    ("a\x00b", "NUL"),
    ("tab\there", "TAB can fake column alignment"),
])
def test_control_characters_in_a_verdict_detail_are_neutralised(payload, why):
    """`verdict_detail` carries CHECKOUT-DERIVED text — file names, declared type
    names — so a repository controls its content.

    `_verdict_marker` replaced only LF while the older `safe_msg` path already
    scrubbed \\r\\n, \\n and \\r, which made the newer channel the weaker one.
    Same class as FR-022: content from the thing under review reaching a
    rendering surface unfiltered.
    """
    f = _f("finding")
    f.verdict, f.verdict_detail = "unchecked", payload
    out = render_plain([f])
    body = out.strip()
    assert len(body.splitlines()) == 1, f"{why}: output split across lines"
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in body), why


def test_ordinary_detail_text_survives_sanitisation():
    """Anti-vacuous control: scrubbing must not eat the evidence."""
    f = _f("finding")
    f.verdict, f.verdict_detail = "confirmed", "declares ThrownDescription = {errName, errCode}"
    assert "declares ThrownDescription = {errName, errCode}" in render_plain([f])
