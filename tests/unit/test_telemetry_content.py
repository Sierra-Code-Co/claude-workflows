"""FR-021: telemetry records sizes, counts and outcomes — never content (T062).

`calls.jsonl` is 30,956 records and growing, on every machine that has ever run
this tool. It is the one artefact here that cannot be un-shipped: by the time
anyone notices a prompt body in it, the file exists on N laptops and in N
backups. So the guard belongs at the WRITER, not at each call site, and it is
worth a test that does not depend on remembering which fields exist.

The reviewers read the diff, so a prompt body contains repository source — and
this repo's own `.coderabbit.yaml` excludes `.claude/projects/**`, which is
conversation logs. One leaked field here is a different category of mistake
from a wrong finding.

DERIVED, not recalled (FR-008a): the shapes come from the allowlists themselves
via `_ALLOWED_KEYS` / `_ALLOWED_GATE_KEYS`, so a field added tomorrow is covered
without anyone remembering to add a case.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest
from review_plan_v2 import telemetry

#: Values planted in every disallowed field. Each is distinctive enough that a
#: substring search cannot match it by accident.
_CONTRABAND = {
    "prompt": "REVIEW THE FOLLOWING DIFF: def f(): SECRETVALUE",
    "messages": "user said SECRETVALUE",
    "diff": "+ const KEY = 'SECRETVALUE'",
    "finding": "SECRETVALUE appears at line 3",
    "response": "here is my finding about SECRETVALUE",
    "body": "SECRETVALUE",
    "content": "SECRETVALUE",
    "text": "SECRETVALUE",
    "file": "web/src/lib/server/SECRETVALUE.ts",
    "message": "SECRETVALUE",
    "stderr": "traceback mentioning SECRETVALUE",
}


@pytest.fixture()
def logdir(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_PLAN_V2_LOG_DIR", str(tmp_path))
    return tmp_path


def test_a_call_record_drops_every_disallowed_field(logdir):
    telemetry.log_call({
        "provider": "deepseek", "model": "deepseek-v4-pro",
        "input_tokens": 1200, "output_tokens": 340, "status_code": 200,
        **_CONTRABAND,
    })
    blob = (logdir / "calls.jsonl").read_text()
    assert "SECRETVALUE" not in blob, "telemetry leaked content into calls.jsonl"
    # Anti-vacuous: the legitimate fields must still be there, or a writer that
    # dropped EVERYTHING would pass the assertion above while logging nothing.
    assert '"provider": "deepseek"' in blob
    assert '"input_tokens": 1200' in blob


def test_a_gate_record_drops_every_disallowed_field(logdir):
    telemetry.log_gate_outcome({
        "gate": "reviewer.correctness", "tier": "probabilistic",
        "blocking": "advisory", "raised": 3, "addressed": 1,
        **_CONTRABAND,
    })
    blob = (logdir / "gates.jsonl").read_text()
    assert "SECRETVALUE" not in blob
    assert '"gate": "reviewer.correctness"' in blob
    assert '"raised": 3' in blob


@pytest.mark.parametrize("writer, filename, allowed", [
    (telemetry.log_call, "calls.jsonl", telemetry._ALLOWED_KEYS),
    (telemetry.log_gate_outcome, "gates.jsonl", telemetry._ALLOWED_GATE_KEYS),
])
def test_only_allowlisted_keys_ever_reach_disk(logdir, writer, filename, allowed):
    """DERIVED from the allowlist itself, so a field added tomorrow is covered.

    A test enumerating today's forbidden names would pass forever while a new
    `prompt_preview` field sailed through — which is the recall-vs-derive
    failure this repo keeps recording.
    """
    writer({**{k: "x" for k in allowed}, **_CONTRABAND, "brand_new_field": "SECRETVALUE"})
    record = json.loads((logdir / filename).read_text().strip().splitlines()[-1])
    assert set(record) <= set(allowed) | {"timestamp"}, (
        f"keys outside the allowlist reached disk: {set(record) - set(allowed)}"
    )


def test_the_allowlists_contain_no_content_bearing_field():
    """Reading the allowlists themselves, so widening one is caught HERE rather
    than after the records exist on every machine that ran the tool."""
    suspicious = {"prompt", "messages", "diff", "body", "content", "text",
                  "response", "finding", "message", "stderr", "stdout", "file",
                  "snippet", "excerpt", "source"}
    for name, allowed in (("calls", telemetry._ALLOWED_KEYS),
                          ("gates", telemetry._ALLOWED_GATE_KEYS)):
        leaked = suspicious & set(allowed)
        assert not leaked, f"{name} allowlist admits content-bearing field(s): {leaked}"


def test_every_record_carries_a_timestamp(logdir):
    """30,956 records were written with `timestamp` in the allowlist and no
    caller passing it, so dating the OpenAI cascade breakage needed file
    line-order as a proxy and "zero failures since the fix" was unprovable.
    Stamped by the writer so no future caller can forget."""
    telemetry.log_call({"provider": "openai"})
    telemetry.log_gate_outcome({"gate": "ruff"})
    for f in ("calls.jsonl", "gates.jsonl"):
        record = json.loads((logdir / f).read_text().strip().splitlines()[-1])
        assert record.get("timestamp"), f"{f} record has no time axis"


def test_the_two_allowlists_are_separate():
    """Sharing one would let a gate record carry `model`, or a call record
    carry a gate id. An allowlist is worth having because it says what THIS
    record shape may contain, not what some record shape may."""
    assert telemetry._ALLOWED_KEYS is not telemetry._ALLOWED_GATE_KEYS
    assert "gate" not in telemetry._ALLOWED_KEYS
    assert "model" not in telemetry._ALLOWED_GATE_KEYS
