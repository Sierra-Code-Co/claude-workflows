"""Portfolio-driven ordering, short-circuit, and advisory exit codes (T040-T042).

Two rules, and each one introduces the risk the other has to cover:

  FR-012  a deterministic failure short-circuits with ZERO LLM calls (SC-006)
  FR-013  only deterministic gates may hard-block

FR-013 is the dangerous one. Making probabilistic findings advisory means a run
can print twenty findings and exit 0 — and "20 findings, exit 0" being
indistinguishable from "0 findings, exit 0" is the exact silent-degradation
shape this whole portfolio exists to close. So the advisory notice is tested as
hard as the exit code, and the anti-vacuous direction (a DETERMINISTIC finding
must still block) gets its own test: a change that made everything advisory
would satisfy every FR-013 test without one.
"""
from __future__ import annotations

import pathlib

import pytest

from review_plan_v2 import output_format
from review_plan_v2.gates import attribution, registry
from review_plan_v2.types import Finding

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def portfolio() -> registry.Registry:
    return registry.load_registry_file(REPO_ROOT / "gates.yml", repo_root=REPO_ROOT)


def _finding(source: str, severity: str = "actionable", message: str = "x") -> Finding:
    return Finding(file="a.py", line=1, line_end=None, severity=severity,
                   category="correctness", message=message, sources=[source])


# --- attribution: which gate produced this? ----------------------------------


@pytest.mark.parametrize("source, expected", [
    ("gitleaks", "gitleaks"),
    ("ruff", "ruff"),
    ("shellcheck", "shellcheck"),
    ("correctness", "reviewer.correctness"),   # reviewers carry a bare name
    ("security", "reviewer.security"),
])
def test_a_finding_is_attributed_to_its_declared_gate(portfolio, source, expected):
    gate = attribution.gate_for(_finding(source), portfolio)
    assert gate is not None and gate.id == expected


def test_a_structural_finding_is_attributed_via_its_rule_id(portfolio):
    """The enumerator reports the BINARY (`ast-grep`); the registry declares
    `structural.<rule-id>`. The rule id is recovered from the message prefix
    that StructuralAnalyzer.parse_output writes."""
    f = _finding("ast-grep", message="[raw-caught-to-logger] logs a raw error")
    gate = attribution.gate_for(f, portfolio)
    assert gate is not None and gate.id == "structural.raw-caught-to-logger"


def test_an_UNATTRIBUTABLE_finding_blocks(portfolio):
    """The rule this module must never break.

    Mis-classifying a deterministic finding as advisory silently stops it
    failing the build and nothing downstream ever says so; the other direction
    is loud and gets fixed. So an unknown source blocks.
    """
    assert attribution.gate_for(_finding("some-future-analyzer"), portfolio) is None
    assert attribution.blocks(_finding("some-future-analyzer"), portfolio) is True


def test_with_no_registry_everything_blocks(portfolio):
    """Downstream repos have not adopted a portfolio. Upgrading this tool must
    not hand them a quietly weaker gate."""
    assert attribution.blocks(_finding("correctness"), None) is True


# --- FR-013: advisory gates do not set a failing exit code -------------------


def test_a_reviewer_finding_no_longer_fails_the_run(portfolio):
    findings = [_finding("correctness")]
    assert output_format.exit_code_for(findings, registry=portfolio) == 0


def test_a_DETERMINISTIC_finding_still_fails_the_run(portfolio):
    """Anti-vacuous, and the one that matters. An implementation that made
    everything advisory would pass every other FR-013 test in this file while
    disabling the portfolio entirely."""
    assert output_format.exit_code_for([_finding("ruff")], registry=portfolio) == 1
    assert output_format.exit_code_for([_finding("gitleaks")], registry=portfolio) == 1


def test_without_a_registry_the_old_behaviour_holds(portfolio):
    """Pre-portfolio repos keep blocking on everything."""
    assert output_format.exit_code_for([_finding("correctness")]) == 1


def test_a_nit_never_blocks_whatever_its_gate(portfolio):
    assert output_format.exit_code_for([_finding("ruff", severity="nit")],
                                       registry=portfolio) == 0


def test_incomplete_coverage_still_outranks_a_clean_advisory_run(portfolio):
    """A run that did not review everything cannot report 0, and that rule must
    survive findings being downgraded to advisory."""
    assert output_format.exit_code_for(
        [_finding("correctness")], failed_task_count=3, registry=portfolio) == 2


# --- FR-013's risk: exit 0 must not look like "clean" ------------------------


def test_exit_zero_with_advisory_findings_is_explained(portfolio):
    """The trade FR-013 must not make.

    Advisory tiering exists so noisy probabilistic gates stop failing builds.
    The moment a run with twenty findings prints the same thing as a run with
    none, the tier has bought nothing and cost the signal.
    """
    findings = [_finding("correctness"), _finding("security"), _finding("tests")]
    assert output_format.exit_code_for(findings, registry=portfolio) == 0

    notice = "\n".join(output_format.render_advisory_notice(findings, portfolio))
    assert "[ADVISORY]" in notice
    assert "3 actionable finding(s)" in notice
    assert "correctness" in notice and "security" in notice
    assert "do NOT fail this run" in notice


def test_a_clean_run_prints_no_advisory_notice(portfolio):
    """Anti-vacuous: a banner on every run is a banner nobody reads."""
    assert output_format.render_advisory_notice([], portfolio) == []
    assert output_format.render_advisory_notice([_finding("ruff")], portfolio) == []


def test_the_notice_reaches_the_rendered_output(portfolio):
    """Delivery, not just construction — the same one-line gap that made
    `needs_manifest=False` a four-times-a-session false positive."""
    findings = [_finding("correctness")]
    rendered = output_format.render_plain(findings, {
        "advisory_notice": output_format.render_advisory_notice(findings, portfolio),
    })
    assert "[ADVISORY]" in rendered


# --- FR-012 / SC-006: a deterministic failure stops before LLM spend ---------


def test_a_blocking_deterministic_finding_triggers_the_short_circuit(portfolio):
    gate = attribution.deterministic_failure([_finding("ruff")], portfolio)
    assert gate is not None and gate.id == "ruff"


def test_an_ADVISORY_finding_does_not_trigger_it(portfolio):
    """Short-circuiting on a probabilistic finding would skip the deterministic
    gates' own output on the strength of the least reliable signal in the run."""
    assert attribution.deterministic_failure([_finding("correctness")], portfolio) is None


def test_a_BLOCKING_PROBABILISTIC_gate_still_does_not_short_circuit():
    """Isolates `is_deterministic` from `blocks`, which the shipped portfolio
    cannot: every reviewer in gates.yml is BOTH probabilistic AND advisory, so
    a test using one cannot say which condition did the work. Deleting the
    `is_deterministic` check left the test above green — caught by mutation,
    not by reading.

    A promoted reviewer is a legal registry (FR-014 allows it with measured
    acceptance), and it must still not short-circuit: FR-012 is about not
    paying for LLM calls a deterministic result already settled, and a
    probabilistic gate is never that result.
    """
    promoted = registry.load_registry({
        "version": 1,
        "gates": [{
            "id": "reviewer.correctness", "tier": "probabilistic",
            "blocking": "blocks", "order": 100, "cost": "llm",
            "failure_proof": "tests/proofs/reviewers.sh",
            "promoted_at": "2026-08-01",
            "acceptance": {"runs": 40, "accepted": 31,
                           "measured_through": "2026-08-01"},
        }],
    }, repo_root=REPO_ROOT)
    assert promoted.gates[0].blocks, "the fixture must actually be blocking"
    assert attribution.deterministic_failure(
        [_finding("correctness")], promoted) is None


def test_a_NIT_does_not_trigger_it(portfolio):
    """Blocking gates block on actionable findings, not on style."""
    assert attribution.deterministic_failure(
        [_finding("ruff", severity="nit")], portfolio) is None


def test_no_registry_means_no_short_circuit(portfolio):
    """Without a declared portfolio there is no basis for deciding which gates
    are deterministic, and guessing would skip reviewers a repo expects to run."""
    assert attribution.deterministic_failure([_finding("ruff")], None) is None


def test_the_short_circuit_names_the_gate(portfolio):
    """`short_circuited: true` leaves the operator guessing which of six
    deterministic gates stopped the run."""
    gate = attribution.deterministic_failure(
        [_finding("correctness"), _finding("shellcheck")], portfolio)
    assert gate is not None and gate.id == "shellcheck"


# --- T043: acceptance material, counts only ----------------------------------


def test_gate_outcomes_record_counts_and_never_content(tmp_path, monkeypatch):
    """FR-021 enforced at the writer, not trusted at each call site.

    A telemetry file that has accumulated message bodies is not fixable after
    the fact — the records are already on disk on every machine that ran it.
    """
    from review_plan_v2 import telemetry

    monkeypatch.setenv("REVIEW_PLAN_V2_LOG_DIR", str(tmp_path))
    telemetry.log_gate_outcome({
        "gate": "reviewer.correctness", "tier": "probabilistic",
        "blocking": "advisory", "raised": 3, "addressed": 1,
        # Everything below must be dropped.
        "message": "a customer name and an AKIA-shaped string",
        "file": "web/src/lib/server/secrets.ts",
        "diff": "- const KEY = ...",
    })
    blob = (tmp_path / "gates.jsonl").read_text()
    assert "reviewer.correctness" in blob and '"raised": 3' in blob
    for leaked in ("customer", "AKIA", "secrets.ts", "const KEY"):
        assert leaked not in blob, f"telemetry leaked {leaked!r}"


def test_acceptance_accumulates_across_runs(tmp_path, monkeypatch):
    from review_plan_v2 import telemetry

    monkeypatch.setenv("REVIEW_PLAN_V2_LOG_DIR", str(tmp_path))
    for raised, addressed in ((3, 1), (2, 2)):
        telemetry.log_gate_outcome({
            "gate": "reviewer.tests", "raised": raised, "addressed": addressed})
    telemetry.log_gate_outcome({"gate": "ruff", "raised": 9, "addressed": 9})

    got = telemetry.acceptance_for("reviewer.tests")
    assert got == {"runs": 2, "raised": 5, "addressed": 3}, (
        "counts must be per-gate; another gate's numbers leaked in"
    )


def test_a_torn_log_line_does_not_discard_the_history(tmp_path, monkeypatch):
    """A killed process can leave a partial line. Losing every prior run to it
    would defeat the point of a running total."""
    from review_plan_v2 import telemetry

    monkeypatch.setenv("REVIEW_PLAN_V2_LOG_DIR", str(tmp_path))
    telemetry.log_gate_outcome({"gate": "reviewer.tests", "raised": 4, "addressed": 2})
    with (tmp_path / "gates.jsonl").open("a") as f:
        f.write('{"gate": "reviewer.tests", "rais\n')
    assert telemetry.acceptance_for("reviewer.tests")["raised"] == 4


def test_a_missing_log_reads_as_zeros(tmp_path, monkeypatch):
    """This informs a judgement call and must never break a review."""
    from review_plan_v2 import telemetry

    monkeypatch.setenv("REVIEW_PLAN_V2_LOG_DIR", str(tmp_path / "nope"))
    assert telemetry.acceptance_for("reviewer.tests") == {
        "runs": 0, "raised": 0, "addressed": 0}


# --- cascade legs belong to their base reviewer ------------------------------


@pytest.mark.parametrize("source", [
    "correctness-cascade-openai",
    "correctness-cascade-google",
])
def test_a_cascade_leg_is_attributed_to_its_BASE_reviewer(portfolio, source):
    """Found by running this tool on its own Phase 6 diff.

    19 actionable findings, 18 advisory, exit 1 — and the nineteenth came from
    a cascade leg alone. `<reviewer>-cascade-<provider>` matched no gate id, so
    it fell to the unattributable-blocks default and FAILED THE RUN: a
    probabilistic gate blocking, which is precisely what FR-013 forbids and
    what this phase exists to prevent.

    The fail-safe default was right. The mapping was incomplete, and only
    exercising the real thing surfaced it — no unit fixture used a cascade name
    because I did not think of one.
    """
    gate = attribution.gate_for(_finding(source), portfolio)
    assert gate is not None and gate.id == "reviewer.correctness"
    assert attribution.blocks(_finding(source), portfolio) is False


def test_an_unknown_source_still_blocks_after_the_cascade_fix(portfolio):
    """Anti-vacuous. Splitting on the marker must not turn the fail-safe into
    "attribute anything vaguely similar" — an unknown gate must still block."""
    assert attribution.blocks(_finding("totally-unknown-analyzer"), portfolio) is True
    assert attribution.blocks(_finding("unknown-cascade-openai"), portfolio) is True
