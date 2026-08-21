"""The repo's own `gates.yml`, loaded and checked as data (T011, T012).

`tests/unit/test_gate_registry.py` proves the LOADER enforces its invariants
against synthetic documents. Nothing proved the file this repo actually ships
satisfies them — and a registry that fails to load in production while its
loader is thoroughly tested is the same "the check works, the thing it checks
was never checked" gap that put a fixture outside its rule's `files:` scope for
a month.

So these run against the real `gates.yml`, at its real path, with the real
repo root.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from review_plan_v2.gates import registry

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GATES_YML = REPO_ROOT / "gates.yml"


@pytest.fixture(scope="module")
def portfolio() -> registry.Registry:
    assert GATES_YML.is_file(), (
        f"{GATES_YML} is missing. Do not skip this test — an absent portfolio "
        f"is the state T011 exists to end, and skipping would report it clean."
    )
    return registry.load_registry_file(GATES_YML, repo_root=REPO_ROOT)


def test_the_shipped_registry_loads(portfolio):
    assert portfolio.version == 1
    assert portfolio.gates, "a portfolio with no gates is not a portfolio"


def test_every_analyzer_and_reviewer_in_the_code_is_declared(portfolio):
    """DERIVED from the code, not from a list I remembered (FR-008a).

    A gate that runs but is not declared is invisible to every rule the
    registry enforces: it can block without acceptance, order after an llm
    gate, or ship with no failure proof, and the registry will still validate
    cleanly because it never heard of it. The dangerous direction is silence,
    so the set is read off the modules that actually exist.
    """
    analyzer_dir = REPO_ROOT / "scripts" / "review_plan_v2" / "analyzers"
    reviewer_dir = REPO_ROOT / "scripts" / "review_plan_v2" / "reviewers"
    expected = {
        p.stem for p in analyzer_dir.glob("*.py")
        if p.stem not in {"__init__", "base"}
    } | {
        f"reviewer.{p.stem}" for p in reviewer_dir.glob("*.py")
        if p.stem not in {"__init__", "base"}
    }
    assert expected, "found no analyzer/reviewer modules — this glob went stale"

    # Structural gates come from `rules/`, not from a module; they have their
    # own derivation in the next test.
    declared = {g.id for g in portfolio.gates if not g.id.startswith("structural.")}

    missing = sorted(expected - declared)
    assert not missing, (
        f"these gates exist in code but are undeclared in gates.yml: {missing}. "
        f"An undeclared gate is exempt from every invariant the registry "
        f"enforces, and nothing else will notice."
    )
    # BOTH directions. Review caught that only `expected - declared` was
    # checked, so a gate whose module had been deleted stayed declared —
    # blocking, with a failure proof, and no code behind it. That is the more
    # dangerous half: the portfolio would assert a check runs when nothing does,
    # which is this spec's own thesis inverted.
    stale = sorted(declared - expected)
    assert not stale, (
        f"these gates are declared in gates.yml but have no analyzer/reviewer "
        f"module: {stale}. A declared gate with no code never runs, while the "
        f"portfolio reports it as covering something."
    )


def test_every_structural_rule_on_disk_is_declared(portfolio):
    """The other half of the derivation, and the one the module glob misses.

    A structural gate's identity comes from `rules/`, not from a Python module —
    `gates/structural.py` runs every rule in that directory — so the test above
    cannot see a newly added rule at all. Dropping a .yml into `rules/` makes it
    run on every review; without this, it would run undeclared, exempt from
    every invariant the registry enforces.
    """
    rule_files = sorted((REPO_ROOT / "rules").glob("*.yml"))
    assert rule_files, "no rules on disk — this glob went stale"

    declared = {g.rule for g in portfolio.gates if g.rule}
    missing = [
        str(p.relative_to(REPO_ROOT)) for p in rule_files
        if str(p.relative_to(REPO_ROOT)) not in declared
    ]
    assert not missing, (
        f"structural rule(s) on disk but undeclared in gates.yml: {missing}. "
        f"They run on every review while being invisible to the portfolio."
    )


def test_the_structural_gate_names_a_rule_that_exists(portfolio):
    """The schema requires `rule` on a structural gate; it cannot check the
    file is there, and a rule path pointing at nothing is a gate that scans
    nothing while reporting clean."""
    structural = [g for g in portfolio.gates if g.id.startswith("structural.")]
    assert structural, "no structural gate declared — completeness has no owner"
    for g in structural:
        assert g.rule, f"{g.id} declares no rule"
        assert (REPO_ROOT / g.rule).is_file(), f"{g.id} rule missing: {g.rule}"


def test_no_probabilistic_gate_blocks(portfolio):
    """FR-014, asserted against the shipped file rather than a fixture.

    None of the four reviewers has an acceptance measurement, and the one hard
    number available argues against promoting them: of 20 findings on
    2026-08-15's containment review, 4 were real and ~10 were the known
    "no tests exist" false positive.
    """
    offenders = [g.id for g in portfolio.gates if not g.is_deterministic and g.blocks]
    assert not offenders, f"probabilistic gate(s) blocking without acceptance: {offenders}"


def test_free_gates_all_order_before_llm_gates(portfolio):
    """FR-012 restated on the real file. The loader enforces this, so this test
    is here to catch a gates.yml edit that reorders by hand — the failure would
    otherwise surface as an unexplained LLM bill."""
    latest_free = max(g.order for g in portfolio.gates if g.cost == "free")
    earliest_llm = min(g.order for g in portfolio.gates if g.cost == "llm")
    assert latest_free < earliest_llm


def test_every_declared_failure_proof_is_executable(portfolio):
    """FR-007 goes one step past the loader's `.is_file()`.

    SC-004 verifies gates by RUNNING these, so a proof that exists but is not
    executable fails at the moment it is needed — during a verification run
    nobody is watching closely.
    """
    import os

    for g in portfolio.gates:
        proof = REPO_ROOT / g.failure_proof
        assert os.access(proof, os.X_OK), (
            f"{g.id} names {g.failure_proof}, which exists but is not "
            f"executable; SC-004 runs it rather than reading it"
        )


def test_advisory_gates_cannot_fail_the_run(portfolio):
    """T042 HAS LANDED — this replaces the divergence pin that preceded it.

    The pin it replaces is worth recording, because it failed in the way this
    file keeps warning about. It called `exit_code_for([finding])` with NO
    registry, asserted the result was 1, and promised to go red when T042
    shipped. T042 shipped and it stayed green — because the no-registry path
    deliberately keeps the old block-everything behaviour for repos without a
    portfolio, so the test was pinning backward compatibility rather than the
    divergence it named.

    A pin has to exercise the SAME CALL SHAPE production uses. This one passes
    the registry, which is what the orchestrator does.
    """
    from review_plan_v2.output_format import exit_code_for
    from review_plan_v2.types import Finding

    def _f(source):
        return Finding(file="a.py", line=1, line_end=None, severity="actionable",
                       category="correctness", message="x", sources=[source])

    assert exit_code_for([_f("correctness")], registry=portfolio) == 0, (
        "an advisory reviewer finding failed the run (FR-013)"
    )
    assert exit_code_for([_f("ruff")], registry=portfolio) == 1, (
        "a deterministic blocking gate stopped failing the run — the portfolio "
        "is no longer enforcing anything"
    )


def test_the_registry_is_parsed_with_safe_load():
    """`gates.yml` is repo-supplied, and this tool reviews other people's repos.

    Review raised arbitrary object construction via `yaml.load` as a security
    finding. Measured: the loader already uses `safe_load`, so the finding was
    wrong — but it was worth a guard, because the day someone swaps it for
    `yaml.load` to support a custom tag, reviewing an untrusted PR becomes
    remote code execution and nothing else in this suite would notice.
    """
    source = (
        REPO_ROOT / "scripts" / "review_plan_v2" / "gates" / "registry.py"
    ).read_text()
    assert "yaml.safe_load" in source
    assert not re.search(r"yaml\.load\(", source), (
        "the gate registry is parsed with yaml.load — a repo-supplied gates.yml "
        "can then construct arbitrary Python objects"
    )


def test_the_divergence_banner_is_gone_now_that_it_is_closed():
    """The banner and the divergence lived and died together, as designed.

    Kept as an assertion rather than deleted outright: a stale warning saying
    the registry does not drive exit codes would be worse than no warning, and
    this is the only thing that would notice it coming back.
    """
    text = GATES_YML.read_text()
    assert "WHAT THIS FILE DOES NOT YET DO" not in text, (
        "the divergence banner is back but T042 has landed — either the banner "
        "is stale or exit codes stopped being portfolio-driven"
    )
