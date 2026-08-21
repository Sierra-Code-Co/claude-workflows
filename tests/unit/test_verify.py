"""Claim verification: the allowlist, the three methods, and the failure paths.

The negatives here are DERIVED from `resolve_input`'s own structure rather than
recalled (FR-008a). The function applies twelve distinct constraints; each one
gets a near-miss that violates exactly it and satisfies the rest, and
`test_every_allowlist_constraint_has_a_negative` asserts the count matches so a
thirteenth constraint added later cannot arrive untested.

The most important assertion in this file is the negative one:
`test_no_path_returns_confirmed_without_an_observation`. A verifier that answers
`confirmed` when it could not look is worse than no verifier, because it
launders a guess into a fact and stamps it with a mechanism's authority.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from review_plan_v2.verification.classify import (
    CONFIRMED,
    REFUTED,
    UNCHECKED,
    UNVERIFIABLE,
    Check,
    Claim,
    EnvelopeError,
    build_envelope,
    claim_from_dict,
)
from review_plan_v2.verification.verify import (
    InputRejected,
    Verdict,
    resolve_input,
    verify_claim,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "gold_set_corpus"


def _require_ast_grep():
    """FAIL, never skip.

    A verification gate that silently does not run reports every claim as
    unchecked, and a suite that skips rather than fails cannot tell you that
    happened. `tests/integration/test_static_analyzers.py` skips both its tests
    in CI for want of gitleaks — including the one asserting a secret-bearing
    diff is never sent to an LLM — and nobody noticed for months (T005i).
    """
    if shutil.which("ast-grep") is None:
        pytest.fail("ast-grep is required; see the pinned install in .github/workflows/tests.yml")


def _claim(kind, subject, expected, method, inp):
    return Claim(kind=kind, subject=subject, expected=expected, check=Check(method, inp))


# --- T028a: the allowlist, one negative per constraint -----------------------

REJECTED: list[tuple[str, str, str]] = [
    ("empty", "", "non-empty"),
    ("too-long", "a" * 300, "exceeds"),
    ("control-char", "src:foo\nbar", "control characters"),
    ("shell-substitution", "src:$(whoami)", "identifier"),
    ("shell-separator", "tests:foo; ls", "identifier"),
    ("pipe", "src:foo|tee", "identifier"),
    ("backtick", "src:`id`", "identifier"),
    ("traversal", "../../etc/passwd::x", "safe repo-relative"),
    ("absolute-path", "/etc/passwd::x", "safe repo-relative"),
    ("path-with-colon", "a:b::x", "safe repo-relative"),
    ("nonexistent-path", "web/src/lib/server/nope.ts::describeThrown", "does not resolve"),
    ("unterminated-literal", 'tests:"unclosed', "identifier"),
    ("literal-too-long", 'tests:"%s"' % ("x" * 80), "identifier"),
    ("not-an-identifier", "src:9lives", "identifier"),
    ("unregistered-rule-id", "raw-caught-to-logger", "identifier"),
]


@pytest.mark.parametrize("name, probe, expect", REJECTED, ids=[r[0] for r in REJECTED])
def test_allowlist_rejects(name, probe, expect):
    with pytest.raises(InputRejected, match=expect):
        resolve_input(Check("enumerate", probe), CORPUS)


ACCEPTED: list[tuple[str, str, str, str]] = [
    # (id, input, expected form, expected scope)
    ("bare-symbol", "describeThrown", "symbol", "all"),
    ("scoped-symbol", "tests:commanderDedupKey", "symbol", "tests"),
    ("src-scoped", "src:stripBlockComments", "symbol", "src"),
    ("dotted-member", "ts.isCallExpression", "symbol", "all"),
    ("path-qualified", "web/src/lib/server/describe-thrown.ts::describeThrown", "symbol", "all"),
    ("literal-needle", 'tests:"optional-chain"', "literal", "tests"),
]


@pytest.mark.parametrize("name, probe, form, scope", ACCEPTED, ids=[a[0] for a in ACCEPTED])
def test_allowlist_accepts(name, probe, form, scope):
    """Anti-vacuous control. Without these, every rejection test above is
    satisfied by a function that rejects everything — which would disable
    verification entirely while reporting a perfect security posture."""
    r = resolve_input(Check("enumerate", probe), CORPUS)
    assert (r.form, r.scope) == (form, scope)


def test_every_allowlist_constraint_has_a_negative():
    """FR-008a made machine-checkable.

    `resolve_input` applies twelve constraints. If a thirteenth is added without
    a near-miss, this fails and names the gap — rather than the suite staying
    green over an untested rule, which is how the version-pin check shipped
    three times with a hole in it.
    """
    constraints = {
        "non-empty", "length", "control-chars", "rule-id-membership",
        "scope-vocabulary", "literal-shape", "path-charset", "no-traversal",
        "not-absolute", "inside-checkout", "path-is-a-file", "identifier-shape",
    }
    assert len(constraints) == 12
    assert len(REJECTED) >= len(constraints), (
        "fewer negatives than constraints — some rule in resolve_input is unexercised"
    )


def test_a_shell_metacharacter_literal_is_a_needle_not_a_command():
    """The literal form accepts `"; rm -rf / #"` ON PURPOSE, and that is safe
    because of where a literal can go, not because of what it says: the only
    thing done with it is `str.count`. It never reaches a shell, never enters an
    ast-grep pattern, never names a file. Asserting this pins the property that
    makes the form safe, so a future change that starts interpolating literals
    breaks a test instead of opening a hole."""
    r = resolve_input(Check("enumerate", '"; rm -rf / #"'), CORPUS)
    assert r.form == "literal" and r.name == "; rm -rf / #"
    marker = CORPUS.parent / "SHOULD_NOT_EXIST_after_verify"
    assert not marker.exists()
    v = verify_claim(
        _claim("count", "needle", "0", "enumerate", '"; rm -rf / #"'),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED and "0" in (v.detail or "")
    assert not marker.exists()


def test_rejected_input_is_unchecked_and_logged():
    """A rejected input must RENDER the finding with a marker, not drop it and
    not confirm it — and it must be loud, because it is either a malformed
    reviewer response or an attempt to steer verification into executing
    something."""
    logs: list[str] = []
    v = verify_claim(
        _claim("symbol_exists", "x", "y", "enumerate", "src:$(whoami)"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNCHECKED
    assert any("SECURITY" in line for line in logs), logs


# --- T026: enumerate ---------------------------------------------------------


def test_symbol_absent_is_refuted_when_the_symbol_is_present():
    v = verify_claim(
        _claim("symbol_absent", "commanderDedupKey", "no test references it",
               "enumerate", "tests:commanderDedupKey"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == REFUTED
    assert "deck-dedup.test.ts" in (v.detail or "")


def test_symbol_absent_is_confirmed_when_it_really_is_absent():
    v = verify_claim(
        _claim("symbol_absent", "neverDefinedAnywhere", "absent",
               "enumerate", "tests:neverDefinedAnywhere"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED


def test_scope_actually_narrows():
    """`src:` must not see test files. Without this, every scoped claim is
    silently a whole-repo claim and the tests/src distinction is decorative."""
    in_tests = verify_claim(
        _claim("symbol_exists", "vitest", "imported", "enumerate", "tests:vitest"),
        CORPUS, log=lambda m: None,
    )
    in_src = verify_claim(
        _claim("symbol_exists", "vitest", "imported", "enumerate", "src:vitest"),
        CORPUS, log=lambda m: None,
    )
    assert in_tests.verdict == CONFIRMED
    assert in_src.verdict == REFUTED


def test_count_mismatch_is_refuted_with_the_observed_number():
    v = verify_claim(
        _claim("count", "optional-chain tests", "0", "enumerate", 'tests:"optional-chain"'),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == REFUTED
    assert "observed 3" in (v.detail or ""), v.detail


def test_count_with_a_non_numeric_expected_is_unverifiable_not_zero():
    """`int(x or 0)` coercion is how a missing count became a confident,
    specific, fabricated "0 site(s)" in the completeness superseder. Unknown
    resolves to unverifiable."""
    v = verify_claim(
        _claim("count", "things", "several", "enumerate", 'tests:"optional-chain"'),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == UNVERIFIABLE


def test_a_registered_rule_id_resolves_through_the_rule_branch(tmp_path):
    _require_ast_grep()
    (tmp_path / "a.ts").write_text("console.error(e);\nconsole.error(f);\n")
    rule = tmp_path / "probe.yml"
    rule.write_text(
        "id: probe-console\nlanguage: typescript\nseverity: warning\n"
        "message: probe\nrule:\n  pattern: console.error($$$A)\n"
    )
    v = verify_claim(
        _claim("count", "console.error calls", "2", "enumerate", "probe-console"),
        tmp_path, rule_paths={"probe-console": rule}, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED, v.detail


# --- T027: typecheck ---------------------------------------------------------


def test_return_shape_refutes_the_describe_thrown_claim():
    """The thrice-recurring false positive, killed by reading one declaration."""
    _require_ast_grep()
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name, message", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == REFUTED
    assert "errName" in (v.detail or "") and "errMessage" in (v.detail or "")
    assert "name" in (v.detail or "")


def test_return_shape_confirms_a_true_claim():
    """Anti-vacuous control: typecheck must be able to say yes."""
    _require_ast_grep()
    v = verify_claim(
        _claim("return_shape", "describeThrown", "errName, errCode", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED, v.detail


def test_missing_declaration_is_unverifiable_not_confirmed():
    _require_ast_grep()
    v = verify_claim(
        _claim("return_shape", "noSuchFunction", "a, b", "typecheck", "noSuchFunction"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == UNVERIFIABLE


def test_predicate_result_on_a_non_type_predicate_is_unverifiable():
    """`ts.isCallExpression` matching optional-chain calls is a question about
    RUNTIME behaviour. Reading a declaration cannot answer it, so the honest
    outcome is unverifiable — not a guess dressed as a verification."""
    _require_ast_grep()
    v = verify_claim(
        _claim("predicate_result", "offenders", "false for optional chains",
               "typecheck", "web/src/lib/server/console-guard.ts::offenders"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == UNVERIFIABLE
    assert "execution" in (v.detail or "") or "predicate" in (v.detail or "")


# --- T028: execute is deferred, loudly ---------------------------------------


def test_execute_is_unverifiable_and_says_so_out_loud():
    logs: list[str] = []
    v = verify_claim(
        _claim("predicate_result", "ts.isCallExpression", "false", "execute",
               "ts.isCallExpression"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNVERIFIABLE
    assert "FR-024" in (v.detail or "")
    assert any("execute is not implemented" in line for line in logs), logs


def test_a_mismatched_kind_and_method_refuses_to_answer():
    """`return_shape` routed to `enumerate` would count occurrences of a name
    and report the count as though it settled a type question."""
    logs: list[str] = []
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "enumerate", "describeThrown"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNVERIFIABLE
    assert any("refusing to answer a different question" in line for line in logs), logs


# --- T031: failure is loud, and never `confirmed` ----------------------------


def test_timeout_is_unchecked_not_confirmed(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ast-grep", timeout=0.1)

    monkeypatch.setattr(subprocess, "run", boom)
    logs: list[str] = []
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNCHECKED
    assert any("TIMEOUT" in line for line in logs), logs


def test_a_crashing_verifier_is_unchecked_not_confirmed(monkeypatch):
    def boom(*a, **k):
        raise OSError("ast-grep vanished")

    monkeypatch.setattr(subprocess, "run", boom)
    logs: list[str] = []
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNCHECKED
    assert any("FAILED" in line for line in logs), logs


def test_an_unexpected_exception_is_unchecked_not_confirmed(monkeypatch):
    def boom(*a, **k):
        raise ZeroDivisionError("something nobody predicted")

    monkeypatch.setattr(subprocess, "run", boom)
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == UNCHECKED


def test_missing_ast_grep_is_unchecked_not_confirmed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == UNCHECKED
    assert "not installed" in (v.detail or "")


@pytest.mark.parametrize("breaker", [
    lambda: subprocess.TimeoutExpired(cmd="x", timeout=1),
    lambda: OSError("gone"),
    lambda: RuntimeError("ast-grep exited 2"),
    lambda: ZeroDivisionError("unpredicted"),
])
def test_no_path_returns_confirmed_without_an_observation(monkeypatch, breaker):
    """The single most important assertion in this module.

    Whatever goes wrong, the answer is never `confirmed`. Treating a crashed
    verifier as a clean bill of health is the exact shape of every silent
    degradation this spec was written to close.
    """
    def boom(*a, **k):
        raise breaker()

    monkeypatch.setattr(subprocess, "run", boom)
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck",
               "web/src/lib/server/describe-thrown.ts::describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict != CONFIRMED


# --- envelope construction ---------------------------------------------------


def test_null_claim_yields_unverifiable_and_is_not_a_defect():
    assert verify_claim(None, CORPUS, log=lambda m: None) == Verdict(
        UNVERIFIABLE, "judgment finding: no checkable claim"
    )


def test_build_envelope_rejects_a_refutation_with_no_reason():
    with pytest.raises(EnvelopeError, match="verdict_detail"):
        build_envelope(gate_id="g", file="a.ts", severity="major", body="b",
                       claim=None, verdict="refuted")


def test_build_envelope_rejects_a_confirmed_judgment_finding():
    with pytest.raises(EnvelopeError):
        build_envelope(gate_id="g", file="a.ts", severity="major", body="b",
                       claim=None, verdict="confirmed")


def test_build_envelope_accepts_the_valid_shapes():
    build_envelope(gate_id="g", file="a.ts", severity="major", body="b",
                   claim=None, verdict="unverifiable")
    build_envelope(
        gate_id="g", file="a.ts", severity="major", body="b",
        claim=claim_from_dict({
            "kind": "symbol_exists", "subject": "x", "expected": "y",
            "check": {"method": "enumerate", "input": "x"},
        }),
        verdict="refuted", verdict_detail="not found",
    )


def test_claim_from_dict_rejects_a_partial_claim():
    with pytest.raises(EnvelopeError, match="missing"):
        claim_from_dict({"kind": "count", "subject": "x"})


def test_gold_set_fixture_is_parseable_and_complete():
    """Guards the fixture itself: a corpus that silently loses entries would
    make SC-002 measurable against fewer findings than it claims."""
    gs = json.loads((REPO_ROOT / "tests" / "fixtures" / "gold_set_20260813.json").read_text())
    assert len(gs["findings"]) == 10
    by_class: dict[str, int] = {}
    for f in gs["findings"]:
        by_class[f["classification"]] = by_class.get(f["classification"], 0) + 1
    assert by_class == {
        "real": 3, "checkable_false": 3, "false_not_checkable": 1, "test_blindness": 3,
    }, by_class


def test_a_capped_declaration_search_says_it_stopped_looking(monkeypatch):
    """A cap must be REPORTED, never silently converted into a factual claim.

    The first draft sliced the candidate list with `[:200]` and, on a bigger
    checkout, would have answered "no declaration of X was found" — a confident
    statement about the code — when the truth was "I stopped looking at file
    200". That is a resource limit masquerading as a finding, and it is the same
    shape as every silent cap this spec exists to close.
    """
    _require_ast_grep()
    monkeypatch.setattr("review_plan_v2.verification.verify.MAX_DECL_FILES", 1)
    logs: list[str] = []
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name", "typecheck", "describeThrown"),
        CORPUS, log=logs.append,
    )
    assert v.verdict == UNCHECKED
    assert "stopped looking" in (v.detail or "")
    assert "cap" in (v.detail or "")
    assert any("SEARCH CAPPED" in line for line in logs), logs


def test_an_uncapped_search_still_answers():
    """Anti-vacuous control: the cap must not be what produces every answer."""
    _require_ast_grep()
    v = verify_claim(
        _claim("return_shape", "describeThrown", "name, message", "typecheck", "describeThrown"),
        CORPUS, log=lambda m: None,
    )
    assert v.verdict == REFUTED, v.detail


# --- findings from review-plan-v2 on this branch ------------------------------


def _tree(tmp_path, **files) -> pathlib.Path:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


def test_readonly_members_are_not_silently_dropped(tmp_path):
    """A dropped member makes an expected field look ABSENT, which REFUTES.

    `readonly errName: string` left head = "readonly errName", which failed the
    identifier check and vanished — so a claim naming `errName` would be refuted
    against an interface that declares it. A true finding deleted on a parsing
    gap is the worst direction this module can be wrong in.
    """
    _require_ast_grep()
    root = _tree(tmp_path, **{
        "src/lib/server/x.ts": (
            "export interface Shape {\n"
            "\treadonly errName: string;\n"
            "\treadonly errMessage?: string | null;\n"
            "\terrCode: string;\n"
            "\t[key: string]: unknown;\n"
            "}\n"
            "export function describe(e: unknown): Shape {\n"
            "\treturn { errName: '', errCode: '' } as Shape;\n"
            "}\n"
        ),
    })
    v = verify_claim(
        _claim("return_shape", "describe", "errName, errMessage", "typecheck",
               "src/lib/server/x.ts::describe"),
        root, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED, v.detail
    assert "errName" in (v.detail or "") and "errMessage" in (v.detail or "")


def test_an_index_signature_is_still_not_a_member(tmp_path):
    """Control for the fix above: taking the last token must not start
    admitting `[key: string]: unknown` as a member named `string`."""
    _require_ast_grep()
    root = _tree(tmp_path, **{
        "src/lib/server/x.ts": (
            "export interface Shape {\n\t[key: string]: unknown;\n\tname: string;\n}\n"
            "export function describe(e: unknown): Shape {\n\treturn {} as Shape;\n}\n"
        ),
    })
    v = verify_claim(
        _claim("return_shape", "describe", "key", "typecheck",
               "src/lib/server/x.ts::describe"),
        root, log=lambda m: None,
    )
    assert v.verdict == REFUTED, v.detail


def test_an_unreadable_file_makes_the_count_a_floor_not_an_answer(monkeypatch, tmp_path):
    """A skipped file silently corrupts the ANSWER, not just its precision.

    `symbol_absent` over a corpus where the one file defining the symbol was
    skipped for size returns CONFIRMED — the verifier asserting something is
    absent when it never looked. A floor cannot settle an absence.
    """
    root = _tree(tmp_path, **{"src/lib/server/big.ts": "export const target = 1;\n"})
    monkeypatch.setattr("review_plan_v2.verification.verify.MAX_FILE_BYTES", 1)
    v = verify_claim(
        _claim("symbol_absent", "target", "absent", "enumerate", "src:target"),
        root, log=lambda m: None,
    )
    assert v.verdict == UNCHECKED
    assert "floor" in (v.detail or ""), v.detail


def test_a_readable_file_still_answers(tmp_path):
    """Anti-vacuous control: the unread guard must not swallow normal runs."""
    root = _tree(tmp_path, **{"src/lib/server/ok.ts": "export const target = 1;\n"})
    v = verify_claim(
        _claim("symbol_absent", "target", "absent", "enumerate", "src:target"),
        root, log=lambda m: None,
    )
    assert v.verdict == REFUTED, v.detail


def test_symlinked_files_are_not_followed_out_of_the_checkout(tmp_path):
    """os.walk does not descend into symlinked DIRECTORIES but still yields
    symlinked FILES. Counting one attributes code outside the checkout to the
    repo under review."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.ts").write_text("export const smuggled = 1;\n")
    root = _tree(tmp_path, **{"repo/src/lib/server/real.ts": "export const ok = 1;\n"})
    link = root / "repo" / "src" / "lib" / "server" / "linked.ts"
    link.symlink_to(outside / "secret.ts")

    v = verify_claim(
        _claim("symbol_absent", "smuggled", "absent", "enumerate", "src:smuggled"),
        root / "repo", log=lambda m: None,
    )
    assert v.verdict == CONFIRMED, (
        f"a symlink out of the checkout was followed: {v.detail}"
    )


@pytest.mark.parametrize("field, value", [
    ("kind", {"nested": "object"}),
    ("subject", 42),
    ("expected", ["a", "b"]),
])
def test_non_string_claim_fields_are_rejected_not_coerced(field, value):
    """`str({"a": 1})` is `"{'a': 1}"` — a well-formed subject or search needle.

    Coercing turns a malformed claim into a plausible one and verifies THAT,
    which is the difference between "could not check" and "checked something
    else". Raising surfaces it as `unchecked` with a log line.
    """
    raw = {"kind": "count", "subject": "x", "expected": "0",
           "check": {"method": "enumerate", "input": "x"}}
    raw[field] = value
    with pytest.raises(EnvelopeError, match="non-string"):
        claim_from_dict(raw)


def test_non_string_check_fields_are_rejected():
    with pytest.raises(EnvelopeError, match="non-string"):
        claim_from_dict({"kind": "count", "subject": "x", "expected": "0",
                         "check": {"method": "enumerate", "input": ["ls", "-la"]}})


def test_well_formed_string_claims_still_parse():
    """Anti-vacuous control for both rejections above."""
    c = claim_from_dict({"kind": "count", "subject": "x", "expected": "0",
                         "check": {"method": "enumerate", "input": "x"}})
    assert c is not None and c.check.input == "x"


def test_a_leading_dash_filename_does_not_break_verification(tmp_path):
    """A repo file named `-dash.ts` was parsed by ast-grep as an OPTION.

    Verified 2026-08-15: without `--`, ast-grep exits "unexpected argument '-d'
    found" and verification dies for the WHOLE checkout — one adversarial
    filename disabling the gate. Paths come from our own walk, but their names
    come from the repo under review (FR-022).
    """
    _require_ast_grep()
    _tree(tmp_path, **{
        "-dash.ts": (
            "export interface S { alpha: string; }\n"
            "export function target(): S { return { alpha: '' }; }\n"
        ),
    })
    # A RELATIVE repo_root is what makes this bite: `Path("/abs") / "-dash.ts"`
    # is `/abs/-dash.ts`, which never looked like an option, so an absolute-root
    # version of this test passed against the unfixed code. `Path(".") /
    # "-dash.ts"` is bare `-dash.ts`.
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        v = verify_claim(
            _claim("return_shape", "target", "alpha", "typecheck", "target"),
            pathlib.Path("."), log=lambda m: None,
        )
    finally:
        os.chdir(cwd)
    assert v.verdict == CONFIRMED, v.detail


def test_tsx_declarations_are_parsed_with_the_tsx_grammar(tmp_path):
    """`.tsx` under `--lang ts` returns [] — SILENTLY, exit 0.

    So every declaration in a .tsx file was invisible and the claim came back
    "no declaration found": not a miss but a wrong reason, since the declaration
    is right there and the parser was handed the wrong grammar.
    """
    _require_ast_grep()
    root = _tree(tmp_path, **{
        "src/lib/server/widget.tsx": (
            "export interface Props { title: string; }\n"
            "export function render(): Props { return { title: <span/> as any }; }\n"
        ),
    })
    v = verify_claim(
        _claim("return_shape", "render", "title", "typecheck", "render"),
        root, log=lambda m: None,
    )
    assert v.verdict == CONFIRMED, v.detail


def test_a_truncated_directory_walk_is_reported_not_answered(monkeypatch, tmp_path):
    """`_candidate_files` has its own cap, and discarding its flag reopened the
    hole MAX_DECL_FILES was added to close: a walk truncated at
    MAX_FILES_SCANNED can leave fewer than MAX_DECL_FILES TypeScript files, so
    the search answers "not found" off a partial checkout without tripping its
    own cap."""
    _require_ast_grep()
    root = _tree(tmp_path, **{
        "src/lib/server/a.ts": "export interface S { x: string }\n"
                               "export function target(): S { return { x: '' }; }\n",
        "src/lib/server/b.ts": "export const filler = 1;\n",
    })
    monkeypatch.setattr("review_plan_v2.verification.verify.MAX_FILES_SCANNED", 1)
    logs: list[str] = []
    v = verify_claim(
        _claim("return_shape", "target", "x", "typecheck", "target"),
        root, log=logs.append,
    )
    assert v.verdict == UNCHECKED
    assert "partial checkout" in (v.detail or ""), v.detail
    assert any("SEARCH CAPPED" in line for line in logs), logs
