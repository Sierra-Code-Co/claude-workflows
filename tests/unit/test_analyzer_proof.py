"""The analyzer proof's own skip handling (T035 follow-up).

A skipped analyzer returns `skipped=True` with ZERO findings, which is
byte-identical to a clean result at every call site. The proof therefore checks
`skipped` on every phase — and the reason this file exists is that it did not.

The check was written three times and correct twice. The restore phase asserted
only `not result.findings`, so an analyzer that stopped running between the
seeded and restore phases printed `ok` for a gate that never executed. That is
the T005i defect, inside the file whose docstring declares in capitals that
skipped is a hard failure.

The per-phase parametrisation below is the point: it is derived from the
structure of the proof (three phases, each calling run()) rather than from the
one phase that happened to be caught. Two of the three would have passed a test
written from recall.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "proofs"))

import analyzer_proof  # noqa: E402


@dataclass
class _Result:
    findings: list = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


class _StubAnalyzer:
    """Detects the seed by content, and can be told to skip on a chosen phase."""

    binary = "true"  # resolvable on PATH, so the install check passes
    applicable_globs = ("*.py",)

    def __init__(self, skip_on: int | None = None):
        self.skip_on = skip_on
        self.calls = 0

    def applicable_files(self, files):
        return list(files)

    def run(self, files, workdir="."):
        self.calls += 1
        if self.calls == self.skip_on:
            return _Result(skipped=True, skip_reason="binary vanished mid-run")
        text = (Path(workdir) / "config.py").read_text()
        if "ghp_" in text:
            return _Result(findings=[_Finding("config.py", "token found")])
        return _Result()


@dataclass
class _Finding:
    file: str
    message: str


@pytest.fixture()
def stub_spec(monkeypatch):
    def install(analyzer):
        spec = dict(analyzer_proof.SEEDS["gitleaks"])
        spec["analyzer"] = lambda: analyzer
        monkeypatch.setitem(analyzer_proof.SEEDS, "gitleaks", spec)
        monkeypatch.setattr(analyzer_proof.shutil, "which", lambda _: "/usr/bin/true")
    return install


def test_a_working_analyzer_passes(stub_spec, capsys):
    """Anti-vacuous control: without it, "always fail" passes every case below."""
    stub_spec(_StubAnalyzer())
    assert analyzer_proof.prove("gitleaks") == 0
    assert "goes red" in capsys.readouterr().out


@pytest.mark.parametrize("phase, label", [(1, "clean"), (2, "seeded"), (3, "restore")])
def test_a_skip_on_any_phase_fails_the_proof(stub_spec, capsys, phase, label):
    """Derived from the proof's structure, not from the bug that was found.

    Phase 3 is the one that shipped broken. Phases 1 and 2 were already correct,
    and a test written from recall would have covered only those — confirming
    the implementation instead of the requirement.
    """
    stub_spec(_StubAnalyzer(skip_on=phase))
    assert analyzer_proof.prove("gitleaks") == 1
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert label in out, f"the failure does not say which phase skipped:\n{out}"


def test_a_scope_mismatch_is_reported_as_a_fixture_bug(stub_spec, capsys):
    """Zero findings because the path matched no glob is not a gate failure, and
    saying so sends the reader to the wrong file."""

    class OutOfScope(_StubAnalyzer):
        def applicable_files(self, files):
            return []

    stub_spec(OutOfScope())
    assert analyzer_proof.prove("gitleaks") == 1
    assert "Fix the fixture path, not the gate" in capsys.readouterr().out
