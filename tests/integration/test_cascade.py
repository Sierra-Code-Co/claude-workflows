"""Cascade dispatch — the configured broad provider + the other frontier provider
on high-risk paths.

Anthropic was dropped from the default cascade — anti-self-grading on Claude-written
code (operator works in Claude Code as the implementation model). DeepSeek was then
dropped outright over data egress on employer repositories. So the candidate set is
{ openai, google } gated on per-provider env vars, MINUS whichever one is running the
broad pass, since a cascade leg duplicating the broad provider is one perspective
billed twice rather than an independent second opinion.

Read that as: with the google default, openai is the only cascade leg.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Restores direct execution (`python3 tests/integration/<file>.py`). pytest gets
# `tests` from pyproject's `pythonpath`, but a direct run has no such help, and
# the `if __name__ == "__main__"` guard at the foot of this file PROMISES that
# path works. Removing these two lines to clear an E402 broke that promise in
# eight modules at once, silently — pinned now by
# tests/unit/test_test_collection.py::test_a_guarded_module_runs_directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# `scripts` too, because this module also imports `review_plan_v2` — as an
# INDENTED import inside a test method, which is why the omission survived: the
# line above satisfies the `support` imports directly below, so the file looks
# bootstrapped, and a direct run only reaches the package import once it is deep
# inside a test. Locally it resolved anyway (the package is pip-installed into
# .venv), so nothing failed here until a fresh clone. Verified: with only
# `tests` on sys.path, `from review_plan_v2.providers import registry` raises
# ModuleNotFoundError.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, make_repo_from_diff, run_v2

REPO = Path(__file__).resolve().parents[2]


FIXTURES = REPO / "tests" / "fixtures"


class CascadeTests(unittest.TestCase):
    """OpenAI is detected by `model: gpt-*` in the request body (collides with
    DeepSeek on the /v1/chat/completions URL — disambiguated by body inspection).
    Google is detected by /v1beta/models/{model}:generateContent path. The
    fixture server re-wraps fixture content into the requesting provider's
    response shape, so a single fixture file authored in (e.g.) DeepSeek's
    shape serves all four providers."""

    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURES / "05-cascade-trigger.diff")
        # Configure high-risk path matching the auth file in the diff
        (self.repo / ".review-plan-v2.yaml").write_text(
            "high_risk_paths:\n  - path: 'src/lib/auth/**'\n    reason: 'auth code'\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_cascade_invokes_a_leg_other_than_the_broad_provider_on_high_risk(self):
        # Renamed from test_cascade_invokes_openai_and_google_on_high_risk. That
        # name asserted a both-legs outcome that is now unreachable by design —
        # whichever provider runs the broad pass is skipped as a cascade leg — so
        # the name described a state the tool refuses to produce. A test name that
        # contradicts the intended behaviour makes the failure below look like the
        # thing it names rather than the real one, which is that no leg engages at
        # all. The body already asserts the correct property: broad present, plus
        # at least one leg that is not the broad provider.
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="05-cascade-trigger",
            env_extra={
                "OPENAI_API_KEY": "test-key",
                "OPENAI_API_BASE": self.base_url,
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_API_BASE": self.base_url,
            },
            timeout=120,
        )
        self.assertIn(result.exit_code, (0, 1), msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        summary = json.loads(lines[-1])
        called = {p["provider"]: p for p in summary.get("providers_called", [])}
        # The broad provider must be present, and at least one cascade leg that
        # is NOT the broad provider must also be present.
        #
        # This asserted openai AND google AND deepseek by name. All three at once
        # is now unreachable: deepseek is not selectable, and whichever provider
        # runs the broad pass is skipped as a cascade leg (a duplicate leg is one
        # perspective billed twice, not a second opinion). So the by-name form
        # could only ever fail, and would keep failing for a stale reason after
        # someone fixes the real bug below.
        #
        # This block used to read "PRE-EXISTING FAILURE … no cascade leg is
        # invoked at all … Left failing on purpose." That was true when written
        # and is not true now: the cascade engages and all three tests in this
        # file pass. The comment outlived the failure it described by one branch,
        # and a stale note claiming a test is deliberately red is worse than no
        # note — it tells the next person to read a genuine regression here as
        # "the known one" and move on, which is the same swallow this file's
        # docstring is about, aimed at a human instead of a log.
        #
        # The history is worth keeping because it says what the assertion is FOR:
        # no leg engaged for as long as the wiring looked like this, across the
        # deepseek removal (baseline called only {deepseek}, after it only
        # {google}, both times the 4 broad reviewers and nothing else). What fixed
        # it was the broad-provider work on this branch — the duplicate-leg skip
        # plus wiring the cascade from the registry rather than from literals.
        # If it goes quiet again, that is a regression and not a known state.
        from review_plan_v2.providers import registry

        broad = registry.DEFAULT_BROAD
        self.assertIn(broad, called, msg=f"providers_called: {summary.get('providers_called')}")

        # EGRESS GUARDS FIRST, and this ordering is load-bearing. Anthropic and DeepSeek
        # are the two providers this tool refuses to send diffs to, for self-grading and
        # for PRC-operated egress respectively. Both checks used to sit BELOW the
        # assertTrue(legs) below — which was then a known, deliberately unfixed
        # failure, and passes now — so
        # unittest aborted the method before either ran. The guard against the thing
        # that actually matters was dead code, hidden behind an unrelated red test, and
        # two reviewers caught it independently. If DeepSeek came back tomorrow this
        # test would have failed with "no cascade leg was invoked" and nobody would have
        # looked further. Anything asserting where data does NOT go belongs before any
        # assertion that is expected to fail.
        #
        # NOT vacuous for want of keys, which a review round asked about: `run_v2`
        # FORCES a key for every tag in `registry.ALL_TAGS` whenever a fixture
        # server is in play (tests/support/runner.py), precisely so that a provider
        # dropped for a missing credential cannot be mistaken for a provider
        # dropped on purpose. anthropic and deepseek therefore arrive here fully
        # credentialed and pointed at the fixture server, and the egress refusal is
        # the only thing keeping them out. The `env_extra` above adds the two base
        # URLs it needs; it is not the source of the keys.
        self.assertNotIn("anthropic", called)
        self.assertNotIn("deepseek", called)

        # Duplicates matter here and the dict above cannot see them: `called` is keyed
        # by provider, so a provider that ran as both broad pass and cascade leg — the
        # exact double-billing this file's docstring warns about — overwrites itself and
        # reads as a single entry. Assert on the raw list.
        raw_called = summary.get("providers_called", [])
        raw_tags = [e.get("provider") if isinstance(e, dict) else e for e in raw_called]
        self.assertCountEqual(
            raw_tags, set(raw_tags),
            msg=f"a provider appears twice in providers_called: {raw_called}",
        )

        # Dialing is not answering. Until 2026-08-13 this test asserted only
        # membership in `providers_called` — an ATTEMPT counter — so it passed
        # every day from 2026-05-09 while the OpenAI leg returned HTTP 400 to
        # all 136 calls it ever made. A cascade that contributes nothing is the
        # failure this test exists to catch, so assert on `succeeded`.
        #
        # ALSO ABOVE assertTrue(legs), for the same reason the egress guards were
        # moved above it. This loop sat below that assertion while it was failing,
        # so unittest aborted the method before it ever ran and it was dead code —
        # the second instance of that defect in this method, in a comment block
        # that had already diagnosed the first. The ordering is kept now that the
        # assertion passes: it is the cheap way to make sure a future regression in
        # the cascade cannot re-hide these checks behind one red line. Anything
        # that must be checked regardless of whether the cascade engaged goes
        # first; whatever it can see, it checks. Here that is the broad provider,
        # whose answering is exactly what the DEAD-LEG work is about.
        for provider, entry in called.items():
            self.assertEqual(
                entry["failed"], 0,
                msg=f"'{provider}' leg reported failures: {entry}; stderr={result.stderr}",
            )
            self.assertGreater(
                entry["succeeded"], 0,
                msg=f"'{provider}' leg was called but never answered: {entry}; stderr={result.stderr}",
            )

        legs = set(called) - {broad}
        self.assertTrue(
            legs,
            msg="no cascade leg was invoked on a high-risk path; "
                f"providers_called={summary.get('providers_called')}",
        )

    def test_the_broad_provider_is_not_also_a_cascade_leg(self):
        """The dedup and its warning, which nothing covered.

        A reviewer flagged the gap and a second one claimed the warning loop had been
        deleted outright — it had not, but nothing proved that either way, which is how
        a claim like that costs a session to refute. So assert the observable behaviour.

        Deliberately its own method rather than assertions bolted onto
        test_cascade_invokes_a_leg_other_than_the_broad_provider_on_high_risk. That
        test carried a known, deliberately unfixed failure when this was written, and
        unittest aborts a method at the first failed assertion — so anything added
        after it would have been dead code. That exact mistake was made in this file
        already, with the DeepSeek egress guards. The failure is fixed and all three
        tests here pass; the split stays, because a separate method is what keeps this
        coverage independent of that one's verdict.

        This asserts on stderr rather than on providers_called on purpose: it must hold
        whether or not the surviving leg ever answers.
        """
        # Bound to a name so the anti-vacuity check below can ask which providers
        # this run actually gave a key to, instead of guessing from the registry.
        keyed_env = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_API_BASE": self.base_url,
            "GEMINI_API_KEY": "test-key",
            "GOOGLE_API_BASE": self.base_url,
        }
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="05-cascade-trigger",
            env_extra=keyed_env,
            timeout=120,
        )
        self.assertIn(result.exit_code, (0, 1), msg=f"stderr={result.stderr}")

        from review_plan_v2.providers import registry

        broad = registry.DEFAULT_BROAD
        # The broad provider must be reported as a skipped leg, with the reason. The
        # reason is the assertion that matters: "no key" and "duplicate of the broad
        # pass" are both skips and only one of them is correct here, since both keys
        # were supplied above.
        # Asserted as a NOTE, not a WARNING, and that distinction is the point. Both
        # keys are supplied above, so nothing is missing here: the broad provider's
        # own leg is dropped by design. The old single warning said "High-risk paths
        # are being reviewed by fewer independent models than configured" for this
        # case too, which under the google default fired on every run and named a
        # shortfall it had not counted.
        self.assertRegex(
            result.stderr,
            rf"NOTE: cascade leg not run — {broad} is already the broad provider",
            msg=f"stderr={result.stderr}",
        )
        self.assertNotRegex(
            result.stderr, r"WARNING: cascade leg unavailable",
            msg=f"both keys were supplied, so nothing is unavailable: {result.stderr}",
        )
        self.assertNotRegex(
            result.stderr, r"WARNING: high-risk paths reviewed by \d+ of",
            msg=f"dropping the duplicate leg is not a shortfall: {result.stderr}",
        )
        # Assert on the machine-readable field too, not just the warning text.
        # Guarded like the other two parse sites in this file. The inline
        # `[...][-1]` raised IndexError on empty stdout, which reads as a test
        # bug rather than "the tool produced no output" and discards stderr —
        # the only place the actual cause is written.
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        summary = json.loads(lines[-1])
        skipped = summary.get("cascade_skipped", [])
        self.assertTrue(any(s.startswith(broad) for s in skipped), msg=f"{skipped}")

        # Anti-vacuity, and this is the assertion that took a probe to get right. The
        # first version checked for a "<reviewer>-cascade-<tag>" task name in the output;
        # task names are not emitted, so it could only pass when a debug print happened
        # to leak one — which is precisely how it passed once and failed once. The real
        # observable is the other direction: the OTHER capable provider has a key here,
        # so it must NOT appear in cascade_skipped. If it did, the cascade was disabled
        # wholesale and the dedup assertions above would hold for the wrong reason.
        #
        # Picked from the tags this run actually SUPPLIED A KEY FOR, not from
        # REVIEW_CAPABLE. The two coincide today because REVIEW_CAPABLE is exactly
        # ("google", "openai") and env_extra above sets both keys — but the
        # coincidence is the fragility: a third capable provider, or a reordering,
        # and `next()` yields a tag with no key here. That tag is then legitimately
        # in cascade_skipped for "no key", this assertion fails, and the failure
        # reads as "the cascade was disabled wholesale" when nothing about the
        # cascade changed. Derived from the keys so adding a provider cannot make
        # this test wrong without also making it unrunnable.
        keyed = tuple(
            t for t in registry.REVIEW_CAPABLE
            if any(v in keyed_env for v in registry.KEY_ENV[t])
        )
        others = [t for t in keyed if t != broad]
        self.assertTrue(
            others,
            msg=f"this test needs a second keyed provider to be non-vacuous; keys "
                f"were supplied for {keyed} and the broad provider is {broad}",
        )
        other = others[0]
        self.assertFalse(
            [s for s in skipped if s.startswith(other)],
            msg=f"{other} was also skipped, so this test would pass vacuously — the "
                f"cascade was off entirely rather than deduplicated: {skipped}",
        )

    def test_no_cascade_flag_disables_frontier_cascade(self):
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers", "--no-cascade",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="05-cascade-trigger",
            env_extra={
                "OPENAI_API_KEY": "test-key",
                "OPENAI_API_BASE": self.base_url,
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_API_BASE": self.base_url,
            },
            timeout=120,
        )
        self.assertIn(result.exit_code, (0, 1), msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        summary = json.loads(lines[-1])
        raw = summary.get("providers_called", [])
        providers = {p["provider"] for p in raw}
        # Check duplicates before collapsing to a set. `{broad}` is satisfied whether
        # the broad provider ran once or five times, so the set alone cannot distinguish
        # "cascade correctly suppressed" from "broad pass billed repeatedly".
        self.assertEqual(
            len(raw), len(providers),
            msg=f"a provider appears more than once in providers_called: {raw}",
        )

        # --no-cascade means NO provider ran beyond the one doing the broad pass.
        # Asserting that exactly, rather than naming openai and google, because
        # the broad provider is configurable: this used to assert `"google" not
        # in providers`, which became self-contradictory the moment google became
        # the broad default — the flag was working and the assertion was wrong.
        from review_plan_v2.providers import registry

        broad = registry.DEFAULT_BROAD
        # This assertion is already anti-vacuous. An earlier version used assertNotIn,
        # where an empty set — nothing reviewed at all — passed; the fix was to assert
        # the exact set, which an empty set cannot satisfy. A follow-up
        # `assertIn(broad, providers)` guarding against that survived the rewrite and
        # was unreachable-if-false, so it is gone rather than left reading as a check.
        self.assertEqual(
            providers, {broad},
            msg=f"--no-cascade must leave only the broad provider ({broad}), and at "
                f"least it: called={sorted(providers)}",
        )


if __name__ == "__main__":
    unittest.main()
