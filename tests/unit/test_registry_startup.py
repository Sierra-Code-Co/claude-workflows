"""Registry load is wired into startup and fails the run loudly (T012).

The load happens BEFORE the diff is captured and long before a provider is
paid, so a malformed portfolio costs nothing. Three states have to stay
distinguishable, and the third is the one that matters:

  valid    -> loads, run proceeds, count is reported
  invalid  -> run STOPS, exit 2, the defect is named
  absent   -> run proceeds, absence is REPORTED

`absent` is tolerated because this tool runs in downstream repos that have not
adopted a portfolio yet, and refusing to review them would be a regression. But
it must never print the same thing as "the portfolio is fine" — that is the
silent-degradation shape the whole spec is about, and here it would mean an
operator believing tiers are enforced when nothing declared any.
"""
from __future__ import annotations

import pathlib
import types

import pytest
from review_plan_v2 import orchestrator

VALID = """\
version: 1
gates:
  - id: gitleaks
    tier: deterministic
    blocking: blocks
    order: 10
    cost: free
    failure_proof: proof.sh
"""


def _args(**over):
    base = dict(config=None, base="main", scope=None, strict_config=False)
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    (tmp_path / "proof.sh").write_text("#!/bin/sh\nexit 1\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_until_registry(repo: pathlib.Path, monkeypatch):
    """Drive `run()` far enough to exercise the registry block, then stop.

    Diff capture is made to fail immediately afterwards so the test never needs
    a git repo, a network, or a provider — the registry block runs first, which
    is exactly the ordering property under test. A registry error must beat this
    sentinel; if it does not, the load moved AFTER diff capture and the
    "before you pay a provider" guarantee is gone.
    """
    from review_plan_v2 import diff_capture

    def boom(*a, **k):
        raise diff_capture.DiffCaptureError("SENTINEL: reached diff capture")

    monkeypatch.setattr(diff_capture, "capture_diff", boom)
    monkeypatch.setattr(orchestrator.config_mod, "load_config", lambda *a, **k: _cfg())
    monkeypatch.setattr(orchestrator, "merge_cli_into_config", lambda args, cfg: cfg)
    return orchestrator.run(_args())


def _cfg():
    return types.SimpleNamespace(
        strict_config=False, base="main", scope=None, path_filters=[],
    )


def test_an_invalid_registry_stops_the_run_before_the_diff(repo, monkeypatch, capsys):
    """Exit 2, and it must beat the diff-capture sentinel."""
    (repo / "gates.yml").write_text(VALID.replace("order: 10", "order: -5"))
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "not a valid gate portfolio" in err
    assert "SENTINEL" not in err, (
        "diff capture ran before the registry was validated, so a malformed "
        "portfolio would cost a diff — and eventually a provider call"
    )


def test_a_dangling_failure_proof_stops_the_run(repo, monkeypatch, capsys):
    """FR-007 enforced at startup, not at proof time. A gate whose proof does
    not exist has never been shown able to fail."""
    (repo / "gates.yml").write_text(VALID.replace("proof.sh", "no-such-proof.sh"))
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "failure_proof" in err
    # The sentinel ALSO exits 2, so `code == 2` alone cannot tell "stopped at
    # the registry" from "printed a complaint and carried on into diff capture".
    # Review caught this; every stop-the-run test in this file needs it.
    assert "SENTINEL" not in err, "the run continued past an invalid registry"


def test_an_ABSOLUTE_failure_proof_stops_the_run(repo, monkeypatch, capsys):
    """T005g reaching the entrypoint. `failure_proof` is EXECUTED by SC-004, so
    a path outside the repo must be refused where the registry is actually
    loaded, not only where the loader is unit-tested.

    Refused by the SCHEMA layer here — it rejects an absolute path textually,
    before containment is ever consulted — so the message names the field
    rather than the repository. That ordering is the design, and it is also why
    the containment layer needs the symlink case below: through this entrypoint
    the schema catches everything containment would, which is exactly how the
    schema pattern itself was found to be untestable through `load_registry`.
    """
    (repo / "gates.yml").write_text(VALID.replace("proof.sh", "/etc/passwd"))
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "not a valid gate portfolio" in err
    assert "failure_proof" in err, "the refusal must name the offending field"
    assert "SENTINEL" not in err


def test_a_SYMLINKED_failure_proof_stops_the_run(repo, monkeypatch, capsys):
    """The shape only the resolved-path layer can see.

    `link/proof.sh` is textually perfect — no leading slash, no `..` segment —
    so the schema accepts it. Only resolving the symlink shows it lands outside
    the repo, and SC-004 would otherwise have executed it.
    """
    import os

    outside = repo.parent / "outside-the-repo"
    outside.mkdir(exist_ok=True)
    (outside / "proof.sh").write_text("#!/bin/sh\nexit 1\n")
    os.symlink(outside, repo / "link")

    (repo / "gates.yml").write_text(VALID.replace("proof.sh", "link/proof.sh"))
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "escapes the repository" in err, (
        "the containment layer did not run; the schema cannot see a symlink, "
        "so nothing else would have caught this"
    )
    assert "SENTINEL" not in err


def test_a_valid_registry_lets_the_run_continue(repo, monkeypatch, capsys):
    """Anti-vacuous control. Without it, a wiring that rejected EVERY registry
    would satisfy all three tests above while disabling the tool entirely."""
    (repo / "gates.yml").write_text(VALID)
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert "SENTINEL" in err, "the run stopped at a valid registry"
    assert code == 2  # the sentinel's own exit, not the registry's
    assert "1 gate(s) declared" in err
    assert "1 blocking" in err


def test_an_absent_registry_is_reported_not_assumed_fine(repo, monkeypatch, capsys):
    """The state this spec exists to make impossible to misread.

    No gates.yml is tolerated — downstream repos have not adopted one — but the
    run must SAY SO. If absence printed nothing, an operator would read a clean
    run as "the declared tiers held" when nothing declared any.
    """
    assert not (repo / "gates.yml").exists()
    code = _run_until_registry(repo, monkeypatch)
    err = capsys.readouterr().err
    assert "NONE DECLARED" in err
    assert "gate portfolio" in err
    # And the run must actually CONTINUE. Review caught that the assertions
    # above hold just as well for an implementation that prints the banner and
    # then treats a missing portfolio as fatal — which would break every
    # downstream repo that has not adopted one, while this test stayed green.
    assert "SENTINEL" in err, (
        "an absent gates.yml stopped the run; it must be tolerated and merely "
        "reported, or downstream repos without a portfolio cannot be reviewed"
    )
    assert code == 2  # the sentinel's own exit, reached only by continuing
