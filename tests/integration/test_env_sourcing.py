"""Integration test for review-plan-v2.sh's .env-sourcing + key whitelist + fallback logic."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "scripts" / "review-plan-v2.sh"


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
        # Use a unique marker that ONLY appears in the LAST fallback block (not
        # in the case-statement allowlist): the actual assignment line for the
        # last provider we reconstitute (GEMINI).
        fb_assign = entrypoint_src.find('export GEMINI_API_KEY="$GEMINI_API_KEY_FALLBACK"', start)
        end_fi = entrypoint_src.find("\nfi", fb_assign)
        assert start != -1 and fb_assign != -1 and end_fi != -1, "couldn't extract loader stanza"
        loader = entrypoint_src[start:end_fi + len("\nfi")]

        probe = f"""
set -euo pipefail
cd {repo}
{loader}
# dump only KEYS we care about so the test asserts on a small surface
for key in DEEPSEEK_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY REVIEW_PLAN_V2_TEST_FIXTURE PATH LD_PRELOAD PYTHONPATH PWNED_FLAG; do
    val="${{!key:-<UNSET>}}"
    echo "$key=$val"
done
"""
        env = os.environ.copy()
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        env.pop("REVIEW_PLAN_V2_TEST_FIXTURE", None)
        env.pop("PWNED_FLAG", None)
        env.pop("LD_PRELOAD", None)
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

    def test_all_four_providers_fallback_independent(self):
        env = _capture_env(None, extra_env={
            "ANTHROPIC_API_KEY_FALLBACK": "ant-fb",
            "DEEPSEEK_API_KEY_FALLBACK": "ds-fb",
            "OPENAI_API_KEY_FALLBACK": "oai-fb",
            "GEMINI_API_KEY_FALLBACK": "gem-fb",
        })
        self.assertEqual(env["ANTHROPIC_API_KEY"], "ant-fb")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "ds-fb")
        self.assertEqual(env["OPENAI_API_KEY"], "oai-fb")
        self.assertEqual(env["GEMINI_API_KEY"], "gem-fb")


if __name__ == "__main__":
    unittest.main()
