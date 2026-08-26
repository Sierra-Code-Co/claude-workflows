"""Integration test for review-plan-v2.sh's .env-sourcing + key whitelist + fallback logic."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# This module was stdlib-only until BaseUrlIsNotLoadableFromTheReviewedRepo needed
# registry.BASE_ENV to derive its cases from the provider list rather than
# hardcoding one. Bootstrapped at module level in the documented form, not with an
# ad-hoc sys.path.insert inside the test method — the first attempt did the latter
# and tests/unit/test_test_collection.py caught it, correctly: the `__main__` guard
# at the foot of this file promises `python3 tests/integration/test_env_sourcing.py`
# works on a fresh clone, and a path fixed up inside one method does not keep that
# promise for the imports of the next one.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.providers import registry

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "scripts" / "review-plan-v2.sh"

# The vars the probe reports back, and — minus PATH/PYTHONPATH — the vars it
# clears from the inherited environment first. One list for both so the two
# cannot drift: a var dumped but not cleared reads the developer's own shell.
#: Base-URL names are DERIVED from registry.BASE_ENV, not listed. The probe only
#: echoes what _DUMPED names, and
#: test_every_base_env_var_the_registry_knows_is_refused iterates BASE_ENV — so a
#: var in one and not the other makes `env.get(var, "<UNSET>")` return the default
#: and the assertion pass without the entrypoint having refused anything. The
#: literal list held GOOGLE_API_BASE and OPENAI_API_BASE only, so two of the four
#: subTests (DEEPSEEK_API_BASE, ANTHROPIC_API_BASE) asserted nothing from the day
#: they were written. A test added to catch a drifting list had drifted from a
#: list; deriving is the only version of it that cannot.
_BASE_VARS = tuple(sorted(v for v in registry.BASE_ENV.values() if v))
_DUMPED = (
    "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
    *_BASE_VARS,
    "REVIEW_PLAN_V2_TEST_FIXTURE",
    "PATH", "LD_PRELOAD", "PYTHONPATH", "PWNED_FLAG",
)
STDERR_KEY = "<stderr>"


def _capture_env(env_file_contents: str | None, extra_env: dict | None = None) -> dict[str, str]:
    """Run a tiny bash probe through the entrypoint's loader logic and return env state.

    Strategy: we can't subclass the entrypoint, so instead we replicate the
    .env loader path by invoking `bash -c` that runs the SAME parser logic
    against a temp git repo + .env, and dumps the resulting env. This tests
    the parser logic in isolation. A separate end-to-end test below verifies
    the full entrypoint hand-off.
    """
    tmp = tempfile.mkdtemp(prefix="rpv2-env-test-")
    try:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        if env_file_contents is not None:
            (repo / ".env").write_text(env_file_contents)

        # Extract the loader + fallback stanzas from the canonical entrypoint
        # and run them under a probe that prints the env afterwards. This pins
        # the contract: whatever the entrypoint loads is what we test against.
        entrypoint_src = ENTRYPOINT.read_text()
        # Capture from `GIT_ROOT=` (start of .env loader) through the close
        # of the DeepSeek fallback block. Must include BOTH the .env parser
        # and the *_API_KEY_FALLBACK reconstitution logic.
        start = entrypoint_src.find("GIT_ROOT=")
        # End the window at the LAST reconstitution block, found by searching for
        # the last one rather than by naming a provider.
        #
        # This was pinned to `export GEMINI_API_KEY="$GEMINI_API_KEY_FALLBACK"` as
        # "the last provider we reconstitute", and then a GOOGLE block was added
        # after it. The window kept ending at GEMINI, so the GOOGLE stanza was
        # outside everything this file tests — a test that silently stopped
        # covering the newest code while still passing, which is the same
        # fail-open shape as the fixture named after one provider and the request
        # parser keyed to one wire format. `rfind` plus the completeness assertion
        # below means the NEXT block added is either covered or loudly missing.
        fb_assign = entrypoint_src.rfind('_API_KEY_FALLBACK"')
        end_fi = entrypoint_src.find("\nfi", fb_assign)
        assert start != -1 and fb_assign != -1 and end_fi != -1, "couldn't extract loader stanza"
        loader = entrypoint_src[start:end_fi + len("\nfi")]

        # Every reconstitution the entrypoint performs must be inside the window.
        # Counted from the assignment lines, not the `if` guards, because the
        # allowlist `case` arms mention the same variable names.
        #
        # Being precise about what this catches, since `rfind` above already
        # extends the window to the last block on its own: this does NOT catch
        # the GOOGLE case that motivated the change (rfind does). It catches the
        # remaining way the window can end early — a reconstitution block that is
        # not contiguous with the others, or one whose `if` nests far enough that
        # `find("\nfi", ...)` lands before it. Cheap, and the failure it prevents
        # is a whole file of tests passing while covering nothing.
        entry_assigns = set(re.findall(
            r'export (\w+_API_KEY)="\$\w+_API_KEY_FALLBACK"', entrypoint_src))
        loader_assigns = set(re.findall(
            r'export (\w+_API_KEY)="\$\w+_API_KEY_FALLBACK"', loader))
        assert entry_assigns == loader_assigns, (
            "the extracted loader stanza is missing reconstitution blocks that the "
            f"entrypoint actually has: {sorted(entry_assigns - loader_assigns)}. "
            "Every test in this file would then pass while asserting nothing about "
            "them. Move the new block adjacent to the others, or widen the window "
            "here."
        )

        probe = f"""
set -euo pipefail
cd {repo}
{loader}
# dump only KEYS we care about so the test asserts on a small surface
for key in {" ".join(_DUMPED)}; do
    val="${{!key:-<UNSET>}}"
    echo "$key=$val"
done
"""
        # Clear every var the probe reports, derived from _DUMPED rather than
        # hand-listed. The hand-listed version omitted GOOGLE_API_KEY, so a
        # developer with one exported in their own shell would see it leak into
        # every "<UNSET>" assertion here — a suite that passes or fails on the
        # operator's environment, which is the machine-dependent shape that cost
        # this repo three months on the `lib/` global-ignore incident. PATH and
        # PYTHONPATH are excluded from the clearing: the probe needs them, and
        # the injection tests assert they are *unchanged*, not absent.
        env = os.environ.copy()
        for var in _DUMPED:
            if var not in ("PATH", "PYTHONPATH"):
                env.pop(var, None)
        # The `*_API_KEY_FALLBACK` names too, and they are the ones that actually
        # bite on this machine. The loader stanza under test RECONSTITUTES each
        # primary key from its fallback (for wrappers that strip the primary —
        # the Claude Code subscription-auth wrapper runs `env -u
        # ANTHROPIC_API_KEY claude`), and the repo's own instructions tell you to
        # `export GEMINI_API_KEY_FALLBACK="$GEMINI_API_KEY"` in ~/.zshrc. So a
        # developer who followed those instructions inherits a fallback the probe
        # never clears, the stanza turns it back into a primary, and every
        # "<UNSET>" assertion here fails — on their machine only. Clearing the
        # primary while leaving the thing that recreates it is the same
        # machine-dependent shape the comment above describes, one variable
        # removed.
        for var in [v for v in env if v.endswith("_API_KEY_FALLBACK")]:
            env.pop(var, None)
        if extra_env:
            env.update(extra_env)

        result = subprocess.run(
            ["bash", "-c", probe], capture_output=True, text=True, env=env, timeout=15,
        )
        if result.returncode != 0:
            raise AssertionError(f"probe failed: rc={result.returncode}\nstderr={result.stderr}\nstdout={result.stdout}")

        out: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v
        # Under a key no env var can have: the parser requires
        # ^[A-Z_][A-Z0-9_]*$, so angle brackets cannot collide. Carried because
        # the *_API_BASE refusal is announced on stderr, and a refusal nothing
        # can assert on is a refusal that can silently become a silent drop.
        out[STDERR_KEY] = result.stderr
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class EnvSourcingTests(unittest.TestCase):
    def test_simple_key_value(self):
        env = _capture_env("DEEPSEEK_API_KEY=sk-real-1234")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-real-1234")

    def test_double_quoted_value_stripped(self):
        env = _capture_env('ANTHROPIC_API_KEY="sk-ant-quoted"')
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-quoted")

    def test_single_quoted_value_stripped(self):
        env = _capture_env("OPENAI_API_KEY='sk-quoted'")
        self.assertEqual(env["OPENAI_API_KEY"], "sk-quoted")

    def test_export_prefix_stripped(self):
        env = _capture_env("export GEMINI_API_KEY=sk-prefixed")
        self.assertEqual(env["GEMINI_API_KEY"], "sk-prefixed")

    def test_comment_lines_skipped(self):
        env = _capture_env("# this is a comment\n   # indented comment too\nDEEPSEEK_API_KEY=sk-only")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-only")

    def test_blank_lines_skipped(self):
        env = _capture_env("\n\nDEEPSEEK_API_KEY=sk-blanks-ok\n\n")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-blanks-ok")

    def test_command_substitution_does_not_execute(self):
        # The classic injection: $(touch /tmp/should-not-exist-pwned)
        # Our parser must NEVER execute this — pwned file should not appear.
        marker = Path(tempfile.gettempdir()) / "rpv2-pwned-marker-test"
        marker.unlink(missing_ok=True)
        env = _capture_env(
            f"DEEPSEEK_API_KEY=$(touch {marker} && echo pwned)\n"
            "OPENAI_API_KEY=sk-control"
        )
        # The literal $(...) text becomes the value (or doesn't, if the grammar
        # rejects it) — what matters is that the file was never created.
        self.assertFalse(marker.exists(), "command substitution executed!")
        # Anti-vacuous control, added when ruff flagged `env` as unused and the
        # unused variable turned out to be the tell: asserting only that a file
        # is ABSENT passes just as well when the parser never ran at all — a
        # crashed entrypoint creates no marker either. The control key proves
        # the parse path executed, without constraining how the injection line
        # itself is treated.
        self.assertEqual(env.get("OPENAI_API_KEY"), "sk-control",
                         "the env parser did not run, so the absence of the "
                         "marker file proves nothing")

    def test_dangerous_keys_rejected_path(self):
        env = _capture_env("PATH=/evil/bin:/usr/bin\nDEEPSEEK_API_KEY=sk-also-here")
        # PATH from .env must not have leaked into our env
        self.assertNotIn("/evil/bin", env.get("PATH", ""))
        # But the legit key still came through
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-also-here")

    def test_dangerous_keys_rejected_ld_preload(self):
        env = _capture_env("LD_PRELOAD=/tmp/evil.so\nDEEPSEEK_API_KEY=sk-good")
        self.assertEqual(env.get("LD_PRELOAD", "<UNSET>"), "<UNSET>")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-good")

    def test_dangerous_keys_rejected_pythonpath(self):
        env = _capture_env("PYTHONPATH=/evil/python\nDEEPSEEK_API_KEY=sk-good")
        # PYTHONPATH from inherited shell may still be set, but the .env value
        # must not have replaced it with /evil/python
        self.assertNotIn("/evil/python", env.get("PYTHONPATH", ""))

    def test_lowercase_key_rejected(self):
        env = _capture_env("api_key=lowercase-not-allowed\nDEEPSEEK_API_KEY=sk-real")
        # `api_key` rejected by the [A-Z_] regex — won't be in our dump
        # (We don't print lowercase-key in the probe, so just assert sk-real
        # came through which proves the parser kept going past the bad line.)
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-real")

    def test_unknown_uppercase_key_rejected_by_whitelist(self):
        # PWNED_FLAG matches the regex [A-Z_][A-Z0-9_]* but isn't in the
        # case-statement whitelist, so it must NOT be exported.
        env = _capture_env("PWNED_FLAG=should-not-export\nDEEPSEEK_API_KEY=sk-keeps-going")
        self.assertEqual(env.get("PWNED_FLAG", "<UNSET>"), "<UNSET>")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-keeps-going")

    def test_review_plan_v2_prefix_allowed(self):
        env = _capture_env("REVIEW_PLAN_V2_TEST_FIXTURE=99-something")
        self.assertEqual(env["REVIEW_PLAN_V2_TEST_FIXTURE"], "99-something")

    def test_no_env_file_is_fine(self):
        env = _capture_env(None)
        # Shouldn't crash; just no model keys imported
        self.assertEqual(env.get("DEEPSEEK_API_KEY", "<UNSET>"), "<UNSET>")


class FallbackReconstitutionTests(unittest.TestCase):
    """Verify that *_API_KEY_FALLBACK env vars reconstitute the primary
    when the primary is empty (the Claude Code wrapper-strip case)."""

    def test_anthropic_fallback_reconstitutes_primary(self):
        # Primary is unset, fallback is set → primary should equal fallback after.
        env = _capture_env(None, extra_env={"ANTHROPIC_API_KEY_FALLBACK": "sk-ant-fb"})
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-fb")

    def test_anthropic_fallback_does_not_overwrite_existing_primary(self):
        env = _capture_env(None, extra_env={
            "ANTHROPIC_API_KEY": "sk-ant-real",
            "ANTHROPIC_API_KEY_FALLBACK": "sk-ant-fb",
        })
        # Primary already set — fallback shouldn't clobber it
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-real")

    def test_deepseek_fallback_reconstitutes_primary(self):
        env = _capture_env(None, extra_env={"DEEPSEEK_API_KEY_FALLBACK": "sk-ds-fb"})
        self.assertEqual(env["DEEPSEEK_API_KEY"], "sk-ds-fb")

    def test_no_fallback_no_primary_stays_unset(self):
        env = _capture_env(None)
        self.assertEqual(env.get("ANTHROPIC_API_KEY", "<UNSET>"), "<UNSET>")
        self.assertEqual(env.get("DEEPSEEK_API_KEY", "<UNSET>"), "<UNSET>")

    def test_dotenv_takes_precedence_over_fallback(self):
        # If .env sets the primary, it shouldn't fall through to the fallback.
        env = _capture_env(
            "ANTHROPIC_API_KEY=sk-from-dotenv",
            extra_env={"ANTHROPIC_API_KEY_FALLBACK": "sk-from-fallback"},
        )
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-from-dotenv")

    def test_openai_fallback_reconstitutes_primary(self):
        env = _capture_env(None, extra_env={"OPENAI_API_KEY_FALLBACK": "sk-oai-fb"})
        self.assertEqual(env["OPENAI_API_KEY"], "sk-oai-fb")

    def test_gemini_fallback_reconstitutes_primary(self):
        env = _capture_env(None, extra_env={"GEMINI_API_KEY_FALLBACK": "sk-gem-fb"})
        self.assertEqual(env["GEMINI_API_KEY"], "sk-gem-fb")

    def test_google_fallback_reconstitutes_primary(self):
        # GOOGLE_API_KEY is the one that matters most and was the one untested.
        # providers/google.py accepts GEMINI_API_KEY *or* GOOGLE_API_KEY, google
        # is registry.DEFAULT_BROAD, and a broad provider with no key refuses the
        # run outright — so a broken reconstitution here is exit 2 on the default
        # configuration, not a degraded run.
        env = _capture_env(None, extra_env={"GOOGLE_API_KEY_FALLBACK": "sk-goog-fb"})
        self.assertEqual(env["GOOGLE_API_KEY"], "sk-goog-fb")

    def test_google_fallback_does_not_overwrite_existing_primary(self):
        env = _capture_env(None, extra_env={
            "GOOGLE_API_KEY": "sk-goog-real",
            "GOOGLE_API_KEY_FALLBACK": "sk-goog-fb",
        })
        self.assertEqual(env["GOOGLE_API_KEY"], "sk-goog-real")

    def test_every_reconstituted_key_is_covered_by_a_test_here(self):
        """Anti-staleness: a new fallback block must not arrive untested.

        GOOGLE's did. It was added to the entrypoint and nothing in this class
        mentioned it, while the loader-extraction window silently ended one block
        earlier — so the code was neither executed nor asserted on, and the file
        stayed green. Derive the expected set from the entrypoint so the next
        addition fails here instead.
        """
        src = ENTRYPOINT.read_text()
        reconstituted = set(re.findall(
            r'export (\w+)_API_KEY="\$\w+_API_KEY_FALLBACK"', src))
        tested = {
            name.replace("test_", "").replace("_fallback_reconstitutes_primary", "").upper()
            for name in dir(self)
            if name.endswith("_fallback_reconstitutes_primary")
        }
        self.assertEqual(
            reconstituted, tested,
            f"entrypoint reconstitutes {sorted(reconstituted)} but this class only "
            f"has a reconstitution test for {sorted(tested)}. Add "
            f"test_<provider>_fallback_reconstitutes_primary for the difference.",
        )

    def test_all_five_providers_fallback_independent(self):
        env = _capture_env(None, extra_env={
            "ANTHROPIC_API_KEY_FALLBACK": "ant-fb",
            "DEEPSEEK_API_KEY_FALLBACK": "ds-fb",
            "OPENAI_API_KEY_FALLBACK": "oai-fb",
            "GEMINI_API_KEY_FALLBACK": "gem-fb",
            "GOOGLE_API_KEY_FALLBACK": "goog-fb",
        })
        self.assertEqual(env["ANTHROPIC_API_KEY"], "ant-fb")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "ds-fb")
        self.assertEqual(env["OPENAI_API_KEY"], "oai-fb")
        self.assertEqual(env["GEMINI_API_KEY"], "gem-fb")
        self.assertEqual(env["GOOGLE_API_KEY"], "goog-fb")


class BaseUrlIsNotLoadableFromTheReviewedRepo(unittest.TestCase):
    """`*_API_BASE` in the reviewed repo's .env must not take effect.

    The file parsed is `$GIT_ROOT/.env` — the root of the repository under
    review. providers/google.py puts the API key in the query string and its
    `_validated_base` accepts any https URL with a netloc, so a base URL from
    that file redirects the operator's key and the diff of every changed file to
    an arbitrary host. Unlike broad_provider, which config.py bounds to
    registry.REVIEW_CAPABLE, nothing out-of-repo bounds a URL.
    """

    def test_google_api_base_from_dotenv_is_refused(self):
        env = _capture_env("GOOGLE_API_BASE=https://attacker.example")
        self.assertEqual(env.get("GOOGLE_API_BASE", "<UNSET>"), "<UNSET>")

    def test_openai_api_base_from_dotenv_is_refused(self):
        # Asserted separately rather than trusting the `*_API_BASE)` glob to
        # generalise: the glob sits above the key arms, and its position is the
        # part that is easy to break.
        env = _capture_env("OPENAI_API_BASE=https://attacker.example")
        self.assertEqual(env.get("OPENAI_API_BASE", "<UNSET>"), "<UNSET>")

    def test_the_refusal_is_announced_not_silent(self):
        # A silent drop and a working override are the same output, and an
        # operator whose proxy stopped applying would diagnose a provider
        # outage. Name the variable in the message so the cause is one line.
        env = _capture_env("GOOGLE_API_BASE=https://attacker.example")
        self.assertIn("GOOGLE_API_BASE", env[STDERR_KEY])
        self.assertIn("refusing", env[STDERR_KEY])

    def test_refusing_a_base_does_not_discard_the_rest_of_the_file(self):
        # `continue`, not an abort: a repo carrying a stale base override still
        # gets its keys loaded, or the fix reads as "the tool stopped seeing my
        # .env at all".
        env = _capture_env(
            "GOOGLE_API_BASE=https://attacker.example\nGOOGLE_API_KEY=sk-real\n")
        self.assertEqual(env["GOOGLE_API_KEY"], "sk-real")
        self.assertEqual(env.get("GOOGLE_API_BASE", "<UNSET>"), "<UNSET>")

    def test_an_operator_exported_base_still_wins(self):
        # The shell is trusted; the reviewed branch is not. Losing this would
        # break the fixture harness, which sets the base via env on every
        # integration test.
        env = _capture_env(None, extra_env={"GOOGLE_API_BASE": "http://127.0.0.1:9999"})
        self.assertEqual(env["GOOGLE_API_BASE"], "http://127.0.0.1:9999")

    def test_a_dotenv_base_cannot_override_an_exported_one(self):
        env = _capture_env(
            "GOOGLE_API_BASE=https://attacker.example",
            extra_env={"GOOGLE_API_BASE": "http://127.0.0.1:9999"},
        )
        self.assertEqual(env["GOOGLE_API_BASE"], "http://127.0.0.1:9999")

    def test_the_probe_reports_every_base_var_the_next_test_iterates(self):
        """Anti-vacuity control for the test below, and it would have been red.

        `env.get(var, "<UNSET>")` cannot distinguish "the entrypoint refused this"
        from "the probe never echoed it", and the probe echoes only _DUMPED. Two of
        the four BASE_ENV vars were missing from the literal list, so two subTests
        below passed against a default. _DUMPED now derives them, and this asserts
        that it did — a future edit that re-hardcodes the list fails HERE, naming
        the var, rather than silently making the next test stop asserting.
        """
        missing = sorted({v for v in registry.BASE_ENV.values() if v} - set(_DUMPED))
        self.assertEqual(
            missing, [],
            msg=f"registry.BASE_ENV names {missing} but the probe does not echo "
                f"them, so the refusal test below would pass vacuously for each.",
        )

    def test_every_base_env_var_the_registry_knows_is_refused(self):
        """Derived from registry.BASE_ENV, so a new provider is covered on arrival."""
        names = [v for v in registry.BASE_ENV.values() if v]
        self.assertTrue(names, "registry.BASE_ENV is empty; this test would be vacuous")
        for var in names:
            with self.subTest(var=var):
                env = _capture_env(f"{var}=https://attacker.example")
                # Assert the key is ABSENT, not that a .get() default came back:
                # the probe echoes every name in _DUMPED (guaranteed for these by
                # the test above), so a missing key here means the probe printed
                # "<UNSET>" for it, which is the entrypoint having refused it.
                self.assertIn(var, env, msg=f"probe did not report {var} at all")
                self.assertEqual(env[var], "<UNSET>")


if __name__ == "__main__":
    unittest.main()
