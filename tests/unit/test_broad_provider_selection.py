"""The broad-pass provider is selectable, DeepSeek is not one of the choices, and the
ways it can be selected wrongly fail loudly.

Two changes are under test, and the second is why the first was not enough.

`deepseek` used to be hardcoded in four reviewer factories and again as a bare string
in three orchestrator dicts and the pricing lookup, so "send this repo's diffs to a
different vendor" was an eight-site edit. Making it configurable fixed the edit but not
the risk: a *default* is what applies when config loading degrades, and the YAML loader
returns early on a machine with no `yq`. So a repo that explicitly declared another
provider still got DeepSeek there, silently. DeepSeek is therefore refused outright
rather than merely defaulted-away, and the default lives in exactly one place.

The tests here are mostly about the silent failures, not the happy path.
"""
from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

# Makes the `if __name__ == "__main__"` guard at the foot of this file true.
# pytest supplies `scripts` on sys.path via pyproject's `pythonpath`, so without
# this the module imports fine under pytest and ModuleNotFounds on a direct run —
# pinned by tests/unit/test_test_collection.py::test_a_guarded_module_runs_directly,
# which is the only reason this was noticed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2 import config as config_mod
from review_plan_v2.orchestrator import _estimate_cost_usd
from review_plan_v2.providers import registry
from review_plan_v2.reviewers import (
    consistency,
    correctness,
    security,
)
from review_plan_v2.reviewers import (
    tests as tests_reviewer,
)
from review_plan_v2.types import Diff, FileChange, HighRiskPath, RunConfig

ALL_FACTORIES = (security, correctness, tests_reviewer, consistency)


def _diff(path: str = "web/src/auth.ts", size: int = 40_000) -> Diff:
    return Diff(
        base_ref="main", head_ref="HEAD",
        files=(FileChange(
            path=path, is_binary=False, is_renamed_from=None,
            added_lines=((1, 100),), diff_text="+" * size, language="ts",
        ),),
    )


class DeepSeekIsGone(unittest.TestCase):
    """The point of the change: not reachable by default, by config, or by omission."""

    def test_it_is_not_review_capable(self):
        self.assertNotIn("deepseek", registry.REVIEW_CAPABLE)

    def test_it_is_not_the_default(self):
        self.assertNotEqual(registry.DEFAULT_BROAD, "deepseek")
        self.assertNotEqual(RunConfig().broad_provider, "deepseek")

    def test_asking_for_it_is_refused_with_the_egress_reason(self):
        """A bare "unknown provider" would read as a typo, not a decision."""
        with self.assertRaises(registry.UnknownProvider) as ctx:
            security.make("deepseek")
        msg = str(ctx.exception)
        self.assertIn("egress", msg)
        for tag in registry.REVIEW_CAPABLE:
            self.assertIn(tag, msg)

    def test_config_declaring_it_keeps_the_default_and_flags_an_error(self):
        cfg = RunConfig()
        with mock.patch("sys.stderr"):
            config_mod._apply_broad_provider(cfg, "deepseek", ".review-plan-v2.yaml")
        self.assertEqual(cfg.broad_provider, registry.DEFAULT_BROAD)
        self.assertTrue(cfg.config_has_error)

    def test_no_reviewer_can_be_built_on_it_via_the_default_path(self):
        for mod in ALL_FACTORIES:
            rv = mod.make()
            self.assertNotEqual(rv.provider_call.__module__.rsplit(".", 1)[-1], "deepseek",
                                msg=mod.__name__)

    def test_its_price_is_retained_for_replay(self):
        """Removing the rate would silently mis-cost historical calls.jsonl.

        Refusing it as a *reviewer* is a policy decision; forgetting what it cost
        is data loss, and the cost tooling reads tags straight out of old logs.
        """
        from review_plan_v2.orchestrator import _PRICING
        self.assertIn("deepseek", _PRICING)
        self.assertIn("deepseek", registry.ALL_TAGS)


class TheDefault(unittest.TestCase):
    def test_it_is_defined_in_exactly_one_place(self):
        """Four literal copies is how the old default outlived the decision to move.

        Every consumer must read registry.DEFAULT_BROAD, so flipping it there
        flips it everywhere. If a factory reintroduces a literal, this fails.
        """
        for mod in ALL_FACTORIES:
            self.assertEqual(mod.make().model,
                             registry.default_model(registry.DEFAULT_BROAD),
                             msg=mod.__name__)
        self.assertEqual(RunConfig().broad_provider, registry.DEFAULT_BROAD)

    def test_the_default_is_itself_review_capable(self):
        # A default outside REVIEW_CAPABLE would make every unconfigured run
        # raise UnknownProvider from inside the reviewer factory.
        self.assertIn(registry.DEFAULT_BROAD, registry.REVIEW_CAPABLE)

    def test_needs_manifest_survives_parameterisation(self):
        # needs_manifest drives whether the change manifest is rendered into the
        # prompt. Losing it while editing the factories would silently stop
        # telling reviewers which files were added or renamed.
        for mod in ALL_FACTORIES:
            self.assertTrue(mod.make().needs_manifest, msg=mod.__name__)
            self.assertTrue(mod.make("openai").needs_manifest, msg=mod.__name__)


class SelectingAProvider(unittest.TestCase):
    def test_each_review_capable_tag_builds_a_reviewer_on_that_provider(self):
        for tag in registry.REVIEW_CAPABLE:
            rv = security.make(tag)
            self.assertEqual(rv.provider_call.__module__.rsplit(".", 1)[-1], tag)
            self.assertEqual(rv.model, registry.default_model(tag))

    def test_an_explicit_model_overrides_the_provider_default(self):
        rv = security.make("google", model="gemini-2.5-pro")
        self.assertEqual(rv.model, "gemini-2.5-pro")

    def test_anthropic_is_refused_with_the_self_grading_reason(self):
        with self.assertRaises(registry.UnknownProvider) as ctx:
            security.make("anthropic")
        self.assertIn("self-grading", str(ctx.exception))

    def test_an_unknown_tag_lists_the_valid_ones(self):
        with self.assertRaises(registry.UnknownProvider) as ctx:
            security.make("gpt6")
        for tag in registry.REVIEW_CAPABLE:
            self.assertIn(tag, str(ctx.exception))


class ConfigValidation(unittest.TestCase):
    """A bad tag is a config error at load, not N provider errors at call time."""

    def _apply(self, raw, prefix=".review-plan-v2.yaml"):
        # `prefix` is the caller-formatted origin label, so pass exactly what
        # load_config passes — including the "env " on the environment one. The
        # callee no longer infers that word from the string's shape.
        cfg = RunConfig()
        with mock.patch("sys.stderr"):
            config_mod._apply_broad_provider(cfg, raw, prefix)
        return cfg

    def test_a_valid_tag_is_applied(self):
        self.assertEqual(self._apply("openai").broad_provider, "openai")

    def test_case_and_surrounding_space_are_tolerated(self):
        self.assertEqual(self._apply("  OpenAI ").broad_provider, "openai")

    def test_a_bad_tag_keeps_the_default_and_flags_a_config_error(self):
        # Keeping the default rather than aborting matters: --strict-config is what
        # turns this into exit 5, and a run without it should still review something.
        cfg = self._apply("bogus")
        self.assertEqual(cfg.broad_provider, registry.DEFAULT_BROAD)
        self.assertTrue(cfg.config_has_error)

    def test_a_non_string_keeps_the_default_and_flags_a_config_error(self):
        cfg = self._apply(7)
        self.assertEqual(cfg.broad_provider, registry.DEFAULT_BROAD)
        self.assertTrue(cfg.config_has_error)

    def test_an_env_var_typo_is_not_blamed_on_the_yaml(self):
        """The operator must be sent to the file that is actually wrong.

        Both origins funnel through one warning path whose default prefix is the
        config file, so an env-var typo reported as a YAML error sends them to edit
        a file that is already correct.
        """
        cfg = self._apply("bogus", prefix="env REVIEW_PLAN_V2_BROAD_PROVIDER")
        joined = " ".join(cfg.config_warnings)
        self.assertIn("env REVIEW_PLAN_V2_BROAD_PROVIDER", joined)
        self.assertNotIn(".review-plan-v2.yaml:", joined)


class TheEnvOverrideDoesNotDependOnYq(unittest.TestCase):
    """REVIEW_PLAN_V2_BROAD_PROVIDER is a plain string and must not need a YAML parser.

    `load_config` bailed early when `shutil.which("yq")` was None, and that bail
    sat above the env override — so on a machine with no yq the documented escape
    hatch was silently dropped, the run reported `[default]`, and a repo that set
    the var to satisfy an egress policy had its diff sent to the default provider
    with nothing saying so. Same shape as the DeepSeek default this branch
    removed, one level out: wrong only when a parser is missing.

    Both yq states are asserted in every case below. Testing only the yq-absent
    branch would pass against a build that ignored the env var everywhere, and
    testing only the present branch is what shipped the bug.
    """

    # The yq-missing warning, matched as a substring. Asserted in _load so that
    # "yq present" and "yq absent" are provably DIFFERENT runs.
    _YQ_MISSING = "yq not installed"

    def _load(self, *, yq: bool, file_value: str | None) -> RunConfig:
        """Load a throwaway repo with yq's presence forced, not inherited.

        `which` is patched in BOTH directions on purpose. Leaving it alone for the
        present case — a `nullcontext` — made that case depend on the host: on a
        machine with no yq, `which("yq")` returns None anyway and the yq=True
        iteration silently ran the degraded path a second time, so a two-state test
        collapsed into one state and the interesting half never executed. That is
        the same "a check that cannot fail reads as coverage" shape this suite is
        about, so the state is asserted below rather than assumed.
        """
        import tempfile
        real_which = shutil.which
        with tempfile.TemporaryDirectory() as td:
            if file_value:
                Path(td, ".review-plan-v2.yaml").write_text(
                    f"broad_provider: {file_value}\n", encoding="utf-8")
            # Only yq's answer is forced; every other lookup keeps its real result,
            # so this does not disable unrelated machinery.
            #
            # The present case needs a REAL yq and skips without one. It read
            # `(real_which("yq") or "/nonexistent/bin/yq")`, which crashed on the
            # very host this whole change exists to serve: config.py invokes bare
            # `["yq", …]` and lets PATH resolve it, so a fabricated `which` result
            # gets the run PAST the `which is None` guard and then straight into
            # `FileNotFoundError: [Errno 2] … 'yq'` out of `_yq_to_json`. Measured
            # with PATH stripped to a temp dir: SUBFAILED(yq=True). Fabricating a
            # path only works if the code under test USES the path it was handed,
            # and this code does not.
            #
            # So the previous fix traded a silent degrade for a hard crash — the
            # same host-dependence, one layer out. A skip is the honest third
            # option: it is counted as a skip rather than read as a pass, and the
            # property that matters on a yq-less machine is the yq=False case,
            # which needs no binary and runs everywhere.
            forced = None
            if yq:
                forced = real_which("yq")
                if forced is None:
                    self.skipTest(
                        "no real yq on PATH, so the yq-PRESENT branch cannot be "
                        "simulated: config.py resolves bare ['yq', …] through PATH, "
                        "not through the value which() returns. The yq-absent half "
                        "of this class still runs and is the half that matters here."
                    )
            with mock.patch.object(
                shutil, "which",
                side_effect=lambda n, *a, **k: (
                    forced if n == "yq" else real_which(n, *a, **k)),
            ), mock.patch("sys.stderr"):
                cfg = config_mod.load_config(td)
        # Prove the branch under test is the branch that ran. Without this the
        # whole class could pass while exercising one path twice.
        joined = " ".join(cfg.config_warnings)
        if yq:
            self.assertNotIn(self._YQ_MISSING, joined,
                             "the yq-present case took the yq-missing branch")
        else:
            self.assertIn(self._YQ_MISSING, joined,
                          "the yq-absent case did not take the yq-missing branch")
        return cfg

    def test_the_env_override_is_honoured_with_or_without_yq(self):
        non_default = next(t for t in registry.REVIEW_CAPABLE if t != registry.DEFAULT_BROAD)
        with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_BROAD_PROVIDER": non_default}):
            for yq in (True, False):
                with self.subTest(yq=yq):
                    cfg = self._load(yq=yq, file_value=None)
                    self.assertEqual(cfg.broad_provider, non_default)
                    # The source label is the operator's only evidence of where
                    # the diff went, so a right answer with a wrong label is
                    # still the bug: the stderr banner reads from this field.
                    self.assertIn("env REVIEW_PLAN_V2_BROAD_PROVIDER",
                                  cfg.broad_provider_source)

    def test_env_still_beats_the_file_when_yq_is_absent(self):
        """Precedence must not invert on the degraded path.

        With no yq the file cannot be read at all, so this asserts the env value
        wins over a file that declares the opposite — the case where a naive fix
        (applying env before the file parse) would silently reverse the rule.
        """
        non_default = next(t for t in registry.REVIEW_CAPABLE if t != registry.DEFAULT_BROAD)
        with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_BROAD_PROVIDER": non_default}):
            for yq in (True, False):
                with self.subTest(yq=yq):
                    cfg = self._load(yq=yq, file_value=registry.DEFAULT_BROAD)
                    self.assertEqual(cfg.broad_provider, non_default)

    def test_the_file_value_is_read_when_the_env_var_is_unset(self):
        """The other half of the precedence rule, and the only test here that
        exercises the yq parse itself.

        Every other case sets the env var, which wins — so all of them would still
        pass against a build that never read `.review-plan-v2.yaml` at all. Without
        this one, "env beats file" is proven only in the sense that env beats
        nothing. Needs real yq, and is skipped rather than faked if the host lacks
        it, because there is nothing to assert about a parser that is not there:
        the yq-absent behaviour is already covered by the cases above.
        """
        if not shutil.which("yq"):
            self.skipTest("needs mikefarah yq to parse the fixture; "
                          "the yq-absent path is covered by the other cases here")
        non_default = next(t for t in registry.REVIEW_CAPABLE if t != registry.DEFAULT_BROAD)
        env = {k: v for k, v in os.environ.items() if k != "REVIEW_PLAN_V2_BROAD_PROVIDER"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = self._load(yq=True, file_value=non_default)
        self.assertEqual(cfg.broad_provider, non_default)
        self.assertIn(".review-plan-v2.yaml", cfg.broad_provider_source)

    def test_an_unset_env_var_still_reports_the_default_as_the_default(self):
        # Anti-vacuity for the two above: proves they are reading the env var
        # rather than passing because some other path happens to yield the same
        # tag. Without this, a build that hardcoded the non-default would pass.
        env = {k: v for k, v in os.environ.items() if k != "REVIEW_PLAN_V2_BROAD_PROVIDER"}
        with mock.patch.dict(os.environ, env, clear=True):
            for yq in (True, False):
                with self.subTest(yq=yq):
                    cfg = self._load(yq=yq, file_value=None)
                    self.assertEqual(cfg.broad_provider, registry.DEFAULT_BROAD)
                    self.assertEqual(cfg.broad_provider_source, "default")


class CostEstimateFollowsTheProvider(unittest.TestCase):
    """--max-cost-usd gates on this number, so a stale rate breaks the cap itself."""

    def setUp(self):
        self.diff = _diff()
        self.hrp = [HighRiskPath(path_glob="web/src/*.ts")]

    def test_a_pricier_broad_provider_estimates_higher(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cheap = _estimate_cost_usd(self.diff, RunConfig(broad_provider="google"))
            dear = _estimate_cost_usd(self.diff, RunConfig(broad_provider="openai"))
        self.assertGreater(dear, cheap)

    def test_the_cascade_leg_duplicating_the_broad_provider_is_not_charged(self):
        """It is not run, so charging for it would trip the cap on phantom spend."""
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "GEMINI_API_KEY": "k"},
                             clear=True):
            google_broad = _estimate_cost_usd(
                self.diff, RunConfig(broad_provider="google", high_risk_paths=self.hrp))

        # A second config named openai_broad_google_leg used to be compared against
        # google_broad here, but it was built with broad_provider="google" and
        # no_cascade=False, which is RunConfig's default — so it was the same config
        # under a different name and the assertEqual could not fail. Two reviewers
        # flagged it independently. The claim it was reaching for is the one below:
        # with google broad, the google leg is suppressed as a duplicate, so dropping
        # its key changes nothing about the estimate.

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True):
            only_openai_key = _estimate_cost_usd(
                self.diff, RunConfig(broad_provider="google", high_risk_paths=self.hrp))
        # google is broad (skipped as a leg) and openai has a key, so this equals
        # the both-keys case: the gemini leg contributes nothing either way.
        self.assertEqual(google_broad, only_openai_key)

    def test_a_cascade_leg_without_a_key_is_not_charged(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            no_keys = _estimate_cost_usd(
                self.diff, RunConfig(broad_provider="google", high_risk_paths=self.hrp))
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True):
            one_key = _estimate_cost_usd(
                self.diff, RunConfig(broad_provider="google", high_risk_paths=self.hrp))
        self.assertGreater(one_key, no_keys)

    def test_a_legacy_caller_passing_no_config_uses_the_current_default(self):
        # cfg=None predates RunConfig being threaded through. It must not fall back
        # to a stale literal rate for a provider that can no longer run.
        with mock.patch.dict(os.environ, {}, clear=True):
            legacy = _estimate_cost_usd(self.diff, None)
            explicit = _estimate_cost_usd(
                self.diff, RunConfig(broad_provider=registry.DEFAULT_BROAD))
        self.assertEqual(legacy, explicit)


class RegistryCounters(unittest.TestCase):
    def test_every_review_capable_tag_is_a_known_tag(self):
        """The orchestrator's per-provider counters are keyed off ALL_TAGS.

        A tag that is selectable but absent from ALL_TAGS becomes a KeyError at the
        END of a run that has already spent every call it was going to spend.
        """
        for tag in registry.REVIEW_CAPABLE:
            self.assertIn(tag, registry.ALL_TAGS)

    def test_every_known_tag_has_a_key_env_var_and_a_price(self):
        from review_plan_v2.orchestrator import _PRICING
        for tag in registry.ALL_TAGS:
            self.assertIn(tag, registry.KEY_ENV, msg=tag)
            self.assertTrue(registry.KEY_ENV[tag], msg=tag)
            self.assertIn(tag, _PRICING, msg=tag)

    def test_refused_and_capable_do_not_overlap(self):
        self.assertFalse(set(registry.REFUSED) & set(registry.REVIEW_CAPABLE))

    def test_every_refused_tag_is_still_a_known_tag(self):
        # Refusal is about who may review, not about forgetting the tag exists.
        for tag in registry.REFUSED:
            self.assertIn(tag, registry.ALL_TAGS, msg=tag)

    def test_has_key_reads_every_env_var_the_provider_accepts(self):
        # Google accepts either name; checking only the first would report a
        # configured provider as unconfigured and refuse the run.
        for var in registry.KEY_ENV["google"]:
            with mock.patch.dict(os.environ, {var: "k"}, clear=True):
                self.assertTrue(registry.has_key("google"), msg=var)
                self.assertEqual(registry.key_var("google"), var)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(registry.has_key("google"))

    def test_an_empty_key_var_counts_as_no_key(self):
        # `FOO=` in a .env or a CI secret that resolved to nothing is the common
        # deployment shape. Treating it as present buys a 401 per file instead of one
        # refusal naming the variable, which is the exact failure mode KEY_ENV exists
        # to prevent.
        for var in registry.KEY_ENV["google"]:
            with mock.patch.dict(os.environ, {var: ""}, clear=True):
                self.assertFalse(registry.has_key("google"), msg=f"{var}= (empty)")
                self.assertIsNone(registry.key_var("google"), msg=f"{var}= (empty)")

    def test_a_whitespace_only_key_var_counts_as_no_key(self):
        """The empty case above was caught by accident; this one was not.

        `""` is falsy, so `os.environ.get(var)` handled it without anybody
        deciding to. `" "` and `"\\n"` are truthy strings, so a key that is a
        trailing continuation in a .env, or `export K="$UNSET "`, was reported as
        a configured provider — the preflight called the leg operable and every
        call it then made returned 401. Same outcome as no key at all, reached
        after spending a review's worth of calls to find out.
        """
        for var in registry.KEY_ENV["google"]:
            for blank in (" ", "\t", "\n", "  \n "):
                with self.subTest(var=var, value=repr(blank)):
                    with mock.patch.dict(os.environ, {var: blank}, clear=True):
                        self.assertFalse(registry.has_key("google"))
                        self.assertIsNone(registry.key_var("google"))

    def test_a_key_with_surrounding_whitespace_still_counts(self):
        """Anti-over-correction control. Stripping is for deciding PRESENCE only:
        a real key that arrived with a trailing newline (`$(cat keyfile)`) is a
        key, and refusing it would turn a working configuration into a
        [DEAD-LEG] refusal."""
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": " sk-real\n"}, clear=True):
            self.assertTrue(registry.has_key("google"))
            self.assertEqual(registry.key_var("google"), "GEMINI_API_KEY")

    def test_selectability_is_declared_in_exactly_one_place(self):
        """`module()` gates on REFUSED, the operator-facing lists gate on
        REVIEW_CAPABLE, and nothing used to require the two to agree — so a tag
        added to _MODULES for pricing or replay (which is why deepseek and
        anthropic are still there at all) and not listed in REFUSED would become
        selectable by accident. The registry asserts this at import; this test is
        what keeps that invariant from being deleted as redundant.
        """
        from review_plan_v2.providers import registry as reg
        selectable = set(reg._MODULES) - set(reg.REFUSED)
        self.assertEqual(
            selectable, set(reg.REVIEW_CAPABLE),
            msg="a known, unrefused provider tag is selectable regardless of "
                "REVIEW_CAPABLE — refuse it with a reason or make it capable",
        )
        for tag in selectable:
            self.assertIsNotNone(reg.module(tag), msg=tag)

    def test_missing_key_hint_names_the_vars_for_a_known_tag(self):
        for tag in registry.ALL_TAGS:
            hint = registry.missing_key_hint(tag)
            self.assertIn(tag, hint, msg=tag)
            for var in registry.KEY_ENV[tag]:
                self.assertIn(var, hint, msg=f"{tag}: {hint}")

    def test_missing_key_hint_degrades_for_an_unregistered_tag(self):
        # This fallback is now unreachable for any tag in ALL_TAGS, because the
        # registry's import-time drift guard requires KEY_ENV to cover all of them.
        # It stays because callers pass operator-supplied strings, and it is tested
        # because "unreachable" was a claim about the current tag set, not about the
        # inputs the function accepts — an untested branch that a config typo can
        # reach is not covered by the guard.
        hint = registry.missing_key_hint("mistral")
        self.assertIn("mistral", hint)
        self.assertIn("no key env var known", hint)


class RegistryInvariantsAreEnforcedAtImport(unittest.TestCase):
    """The drift guards, exercised rather than assumed.

    Both fire at import, so they cannot be triggered against the live module. Each
    test re-executes the module source with one line perturbed, which is also the
    only way to prove the guard message names the real problem.
    """

    def _exec_with(self, old: str, new: str):
        # Explicit encoding: read_text() defaults to the platform preference, and a
        # Python source file is UTF-8 by definition. registry.py has non-ASCII in its
        # comments (em dashes), so a cp1252 default would raise UnicodeDecodeError
        # here rather than anywhere near the thing being tested.
        original = Path(registry.__file__).read_text(encoding="utf-8")
        # Check the patch target on the ORIGINAL text, before replacing, and check the
        # count. The previous form — assertNotIn(old, src.split(new)[0]) on the already
        # patched source — could not fail, and two reviewers caught it independently.
        # It passes when `old` is absent (it is nowhere in the file, so it is not in any
        # prefix of it), and it passes when `old` occurs twice (split()[0] is the text
        # BEFORE the replacement, and the surviving second occurrence is after it). So
        # both failure modes it named in its own message were the two it could not
        # detect: a stale patch target would have made every test in this class pass by
        # exec'ing an unperturbed module, which raises nothing, and the assertRaises
        # below would then have been the only thing failing — pointing at the guard
        # rather than at the typo.
        self.assertEqual(
            original.count(old), 1,
            msg=f"patch target must appear exactly once in registry.py, found "
                f"{original.count(old)}: {old!r}",
        )
        src = original.replace(old, new, 1)
        # `"from . import "` only, not the whole line with its provider list spelled
        # out. The list was written in full here, which is the same
        # hardcoded-copy-of-an-upstream-list defect this class exists to catch —
        # committed inside the machinery that catches it. Add or remove a provider
        # in registry.py's relative import and this replacement silently matches
        # nothing, the exec'd module keeps a relative import with no package
        # context, and every test in the class dies with `ImportError: attempted
        # relative import with no known parent package` — an error that names
        # neither the drift check nor the list that drifted.
        #
        # Counted for the same reason the patch target above is counted: a
        # replacement that quietly does nothing is how this class goes vacuous.
        relative = "from . import "
        self.assertEqual(
            src.count(relative), 1,
            msg=f"expected exactly one {relative!r} in registry.py, found "
                f"{src.count(relative)}; the rewrite below would be ambiguous",
        )
        src = src.replace(relative, "from review_plan_v2.providers import ", 1)
        # EVERY relative import rewritten, not just the one form counted above.
        # `from .x import y` added to registry.py later would survive the
        # replacement, and `exec` would raise ImportError("attempted relative
        # import with no known parent package") instead of the RuntimeError this
        # test is about — red for a reason that has nothing to do with provider
        # drift, and the perturbation would never have been evaluated at all.
        # Named here so the failure says which line to rewrite.
        leftover = [ln for ln in src.splitlines() if ln.lstrip().startswith("from .")]
        self.assertFalse(
            leftover,
            msg=f"registry.py has a relative import this rewrite does not handle: "
                f"{leftover}; exec would raise ImportError before the drift guard runs",
        )
        with self.assertRaises(RuntimeError) as ctx:
            exec(compile(src, "registry_perturbed.py", "exec"), {"__name__": "perturbed"})
        return str(ctx.exception)

    def test_a_tag_added_to_all_tags_alone_refuses_to_import(self):
        msg = self._exec_with(
            'ALL_TAGS: tuple[str, ...] = ("deepseek", "openai", "google", "anthropic")',
            'ALL_TAGS: tuple[str, ...] = ("deepseek", "openai", "google", "anthropic", "mistral")',
        )
        self.assertIn("drift", msg)
        self.assertIn("mistral", msg)

    def test_a_bare_string_key_var_refuses_to_import(self):
        # The whole point: a bare string iterates as characters, so the harness would
        # set env["O"], env["P"], env["E"]… and leave OPENAI_API_KEY unset, and
        # openai's tests would pass by never running.
        msg = self._exec_with('"openai": ("OPENAI_API_KEY",),', '"openai": "OPENAI_API_KEY",')
        self.assertIn("KEY_ENV", msg)
        self.assertIn("tuple", msg)

    def test_a_non_string_base_var_refuses_to_import(self):
        # The harness uses this value directly as an env var NAME, so None becomes
        # env[None] = url, which raises from inside subprocess about environment keys
        # and says nothing about this dict.
        msg = self._exec_with('"openai": "OPENAI_API_BASE",', '"openai": None,')
        self.assertIn("BASE_ENV", msg)
        self.assertIn("non-empty str", msg)

    def test_an_empty_base_var_refuses_to_import(self):
        # Distinct from None: an empty name is a str, so a type check alone passes it,
        # and it would set a variable with no name rather than failing.
        msg = self._exec_with('"openai": "OPENAI_API_BASE",', '"openai": "",')
        self.assertIn("BASE_ENV", msg)

    def test_the_patch_target_guard_itself_fails_on_a_stale_target(self):
        """The guard added after two reviewers found the old one could not fail.

        If this class's patch targets ever drift out of registry.py, every test in it
        must fail here — naming the stale string — rather than exec'ing an unperturbed
        module and reporting "RuntimeError not raised", which points at the guard
        instead of at the typo.
        """
        with self.assertRaises(AssertionError) as ctx:
            self._exec_with("this string is not in registry.py", "irrelevant")
        self.assertIn("exactly once", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
