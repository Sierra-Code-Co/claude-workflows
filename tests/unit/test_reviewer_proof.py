"""Anti-vacuous controls for the reviewer failure proof (T036).

The proof itself needs a live provider and costs money, so it runs at most once
per push and exits UNPROVEN without a key. These controls need neither: they
substitute a degenerate reviewer and assert the proof rejects it.

Both degenerate shapes are real failure modes, not invented ones:

  * BLIND — `reasoning_effort=none` made latency, cost and error rate all improve
    while the reviewers returned zero findings on both planted-bug fixtures.
    Nothing failed, because nothing was checking that a known bug was still found.
  * INDISCRIMINATE — the opposite degeneracy, and the reason the proof compares
    the two fixtures rather than only asserting "found something". A reviewer
    that flags every diff satisfies "the planted bug was found" perfectly.

Without these, the proof could stop discriminating and nobody would learn until
the next `reasoning_effort`-shaped change shipped.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "proofs"))

import reviewer_proof  # noqa: E402

from review_plan_v2.reviewers import security  # noqa: E402


@dataclass
class _Finding:
    """The shape a reviewer actually returns.

    The stubs originally used bare strings, and the content assertion caught it
    immediately — `getattr(str, "message", "")` is `""`, so a stub that looked
    like it named the SQL injection matched nothing. A test double that cannot
    fail the way the real object can is testing the double.
    """

    message: str
    category: str = "security"


class _Fixed:
    """A reviewer that returns the same findings regardless of input."""

    def __init__(self, findings: list):
        self._findings = findings

    def run(self, chunk):  # noqa: ARG002 - the point is that input is ignored
        return list(self._findings)


@pytest.fixture()
def live_key(monkeypatch):
    """Satisfy the key check without making a call — every reviewer is stubbed."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key-no-call-is-made")


def test_a_blind_reviewer_fails_the_proof(live_key, monkeypatch, capsys):
    monkeypatch.setattr(security, "make", lambda *a, **k: _Fixed([]))
    assert reviewer_proof.main() == 1
    assert "ZERO findings" in capsys.readouterr().out


def test_an_indiscriminate_reviewer_fails_the_proof(live_key, monkeypatch, capsys):
    monkeypatch.setattr(security, "make", lambda *a, **k: _Fixed([_Finding("a"), _Finding("b"), _Finding("c")]))
    assert reviewer_proof.main() == 1
    assert "no discrimination" in capsys.readouterr().out


def test_a_discriminating_reviewer_passes(live_key, monkeypatch):
    """Anti-vacuous control for the two above: "reject everything" must not pass."""
    calls = {"n": 0}

    class Discriminating:
        def run(self, chunk):  # noqa: ARG002
            calls["n"] += 1
            return [_Finding("unparameterised SQL injection in the query")] if calls["n"] == 1 else []

    monkeypatch.setattr(security, "make", lambda *a, **k: Discriminating())
    assert reviewer_proof.main() == 0
    # Both fixtures must actually be reviewed. Without this, a main() that
    # returned 0 without ever calling the reviewer — or that compared the
    # planted diff against itself — would pass this control.
    assert calls["n"] == 2, f"the reviewer was invoked {calls['n']} time(s), not 2"


def test_a_generic_nit_on_the_planted_diff_is_not_enough(live_key, monkeypatch, capsys):
    """Discrimination by COUNT is satisfied by a reviewer that says something
    irrelevant about the buggy file and nothing about the clean one — which is
    exactly as blind as reasoning_effort=none was, and would have passed."""
    calls = {"n": 0}

    class Irrelevant:
        def run(self, chunk):  # noqa: ARG002
            calls["n"] += 1
            return [_Finding("prefer const over let", category="style")] if calls["n"] == 1 else []

    monkeypatch.setattr(security, "make", lambda *a, **k: Irrelevant())
    assert reviewer_proof.main() == 1
    assert "none of them is about the seeded SQL injection" in capsys.readouterr().out


def test_a_provider_error_is_unproven_not_failure(live_key, monkeypatch, capsys):
    """A rate limit and a blind reviewer must not print the same verdict."""

    class Broken:
        def run(self, chunk):  # noqa: ARG002
            raise RuntimeError("429 rate limited")

    monkeypatch.setattr(security, "make", lambda *a, **k: Broken())
    assert reviewer_proof.main() == reviewer_proof.EXIT_UNPROVEN
    out = capsys.readouterr().out
    assert "UNPROVEN" in out and "429" in out


def test_a_missing_key_reports_unproven_not_success(monkeypatch, capsys):
    """The distinction the whole UNPROVEN protocol rests on.

    Returning 0 here would make "we had no key" indistinguishable from "the
    reviewers found the planted bug" in every log and every CI summary.
    """
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert reviewer_proof.main() == reviewer_proof.EXIT_UNPROVEN
    assert "UNPROVEN" in capsys.readouterr().out


def test_unproven_is_not_the_success_code():
    assert reviewer_proof.EXIT_UNPROVEN != 0


def test_the_double_carries_the_fields_the_proof_reads_on_a_real_finding():
    """A test double that drifts from the real type tests the double.

    The proof matches on `.message` and `.category`. If the production Finding
    ever renames either, every test here keeps passing against `_Finding` while
    the live proof silently stops matching and reports the reviewer blind —
    which is a FAILING proof for a working reviewer, the worst direction.
    """
    from review_plan_v2.types import Finding

    real = Finding(
        file="a.ts", line=1, line_end=None, severity="actionable",
        category="security", message="sql injection", sources=["security"],
    )
    for attr in ("message", "category"):
        assert hasattr(real, attr), f"production Finding has no {attr!r}"
        assert hasattr(_Finding("x"), attr), f"the double has no {attr!r}"
