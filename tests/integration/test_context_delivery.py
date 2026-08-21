"""The context actually reaches the provider (T045, T046, T047, FR-010, FR-011).

Every unit test in `test_reviewer_context.py` proves the assembler builds the
right payload. None of them proves the payload is SENT — and that gap is not
hypothetical: T047's defect was one constructor flag wide. The manifest was
built correctly for the entire period the "no tests exist" false positive was
firing four times a session, because `needs_manifest=False` meant the reviewer
that raises it never saw the manifest that contradicts it.

So these tests run the real orchestrator as a subprocess against the fixture
server and read the bodies that arrived over HTTP. What is asserted is what a
provider would have received.

The repository here is built commit-by-commit rather than by applying a diff to
an empty tree: the point is a hunk that shows PART of a file, and a whole-file
addition has no outside-the-window for a definition to hide in.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from support import fixture_server as fs
from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, run_v2


DESCRIBE_THROWN = """\
export interface ThrownDescription {
\terrName: string;
\terrMessage: string;
\terrCode: string | null;
}

export function describeThrown(e: unknown): ThrownDescription {
\treturn { errName: 'Error', errMessage: String(e), errCode: null };
}
"""

CALLER_BEFORE = """\
import { describeThrown } from './describe-thrown';

export function logIt(e: unknown): void {
\tconsole.error('before');
}
"""

CALLER_AFTER = """\
import { describeThrown } from './describe-thrown';

export function logIt(e: unknown): void {
\tconsole.error('ctx:', describeThrown(e).errMessage);
}
"""

CONVENTIONS = "Never pass a raw caught value to a logger. Use describeThrown.\n"

#: Full repo-relative path, so prompt matching can anchor on the `[File:` header.
CALLER_PATH = "web/src/lib/server/caller.ts"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _build_repo(tmp: Path) -> Path:
    src = tmp / "web" / "src" / "lib" / "server"
    src.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=tmp)
    _git("config", "user.email", "test@example.com", cwd=tmp)
    _git("config", "user.name", "Test", cwd=tmp)

    (src / "describe-thrown.ts").write_text(DESCRIBE_THROWN)
    (src / "caller.ts").write_text(CALLER_BEFORE)
    (tmp / "CONVENTIONS.md").write_text(CONVENTIONS)
    (tmp / ".review-plan-v2.yaml").write_text(
        "always_include_files:\n  - CONVENTIONS.md\n"
        "import_aliases:\n  $lib: web/src/lib\n"
    )
    _git("add", "-A", cwd=tmp)
    _git("commit", "-q", "-m", "base", cwd=tmp)

    _git("checkout", "-q", "-b", "feature", cwd=tmp)
    # Change ONE line, and add a test file alongside it.
    (src / "caller.ts").write_text(CALLER_AFTER)
    (src / "caller.test.ts").write_text(
        "import { describe, expect, it } from 'vitest';\n"
        "import { logIt } from './caller';\n\n"
        "describe('logIt', () => { it('logs', () => { expect(logIt).toBeTruthy(); }); });\n"
    )
    _git("add", "-A", cwd=tmp)
    _git("commit", "-q", "-m", "use describeThrown", cwd=tmp)
    return tmp


class ContextDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FixtureServer()
        cls.base_url = cls.server.start()
        cls.tmp = Path(tempfile.mkdtemp(prefix="rpv2-context-repo-"))
        _build_repo(cls.tmp)
        fs.reset_request_bodies()
        cls.result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", "--no-verify",
            cwd=cls.tmp, fixture_base_url=cls.base_url, fixture_name="01-clean",
            timeout=180,
        )
        cls.bodies = fs.get_request_bodies()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cleanup_repo(cls.tmp)

    def _prompts_for(self, path: str, reviewer: str | None = None) -> list[str]:
        """User prompts whose FILE UNDER REVIEW is `path`, optionally for one reviewer.

        Two filters, and both were learned the hard way by mutating the code
        these tests claim to pin.

        The reviewer filter: an `any()` across all four reviewers is satisfied by
        whichever one happens to be configured correctly, so an assertion
        written that way passes throughout the period the tests reviewer is the
        one flying blind.

        The `[File:` anchor: a bare substring search for "caller.ts" also
        matched the prompt for `caller.test.ts`, because that file imports
        `./caller` and the context block therefore CITES the path. The test
        passed with the manifest disabled by reading the wrong prompt — this
        feature made the old style of matching ambiguous, which is a nice
        demonstration that adding context to a prompt changes what a test that
        greps the prompt is actually measuring.
        """
        out = []
        for raw in self.bodies:
            try:
                messages = json.loads(raw).get("messages") or []
            except json.JSONDecodeError:
                continue
            system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
            if reviewer is not None and f"**{reviewer}** code reviewer" not in system:
                continue
            user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
            if f"[File: {path} |" in user:
                out.append(user)
        return out

    def test_the_run_reached_the_providers_at_all(self):
        """Anti-vacuous control. Every assertion below is about prompt contents,
        and "no prompts were sent" satisfies a `not in` check trivially."""
        self.assertGreater(len(self.bodies), 0,
                           msg=f"stdout={self.result.stdout}\nstderr={self.result.stderr}")

    def test_the_imported_definition_is_delivered(self):
        """T046 / #19 end to end. `ThrownDescription` is named nowhere in the
        diff — it is reached through describeThrown's return type, one import
        hop away. This is the fact gold-set G6 asserted wrongly."""
        prompts = self._prompts_for(CALLER_PATH)
        self.assertTrue(prompts, "no reviewer prompt mentioned caller.ts")
        # `errCode` appears ONLY in the interface, never in the diff. `errMessage`
        # would have been the obvious needle and is worthless here: the changed
        # line is `describeThrown(e).errMessage`, so it is present whether or not
        # any context was attached. That version of this test passed with context
        # delivery disabled.
        self.assertTrue(
            any("errCode: string | null" in p for p in prompts),
            "the definition that refutes the describeThrown false positive was "
            "assembled but never sent",
        )

    def test_the_standing_file_is_delivered(self):
        """T045 / #18: always_include_files, read from real config by the real
        config loader."""
        prompts = self._prompts_for(CALLER_PATH)
        self.assertTrue(any("Never pass a raw caught value" in p for p in prompts))

    def test_the_test_file_is_named_to_the_tests_reviewer_specifically(self):
        """T047 / FR-010, scoped to the reviewer that raises the finding.

        `tests` is the one that says "no test coverage was added", and it is the
        one that had `needs_manifest=False`. Asserting across all reviewers
        would be satisfied by `consistency`, which already received the manifest
        and never raised the finding.
        """
        prompts = self._prompts_for(CALLER_PATH, reviewer="tests")
        self.assertTrue(prompts, "the tests reviewer was never asked about caller.ts")
        self.assertTrue(
            any("caller.test.ts" in p for p in prompts),
            "the tests reviewer was not told a test file is in this change",
        )

    def test_the_run_reports_no_context_gaps(self):
        """FR-011's other direction. Every import in this repo resolves and the
        standing glob matches, so a [CONTEXT-GAP] line here would mean the
        harness is reporting a blind spot it does not have — which would train
        the operator to ignore the banner."""
        self.assertNotIn("[CONTEXT-GAP]", self.result.stdout,
                         msg=self.result.stdout)


class ContextOptOutTests(unittest.TestCase):
    """--no-context is allowed. --no-context SILENTLY is not."""

    @classmethod
    def setUpClass(cls):
        cls.server = FixtureServer()
        cls.base_url = cls.server.start()
        cls.tmp = Path(tempfile.mkdtemp(prefix="rpv2-context-off-repo-"))
        _build_repo(cls.tmp)
        fs.reset_request_bodies()
        cls.result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", "--no-verify",
            "--no-context",
            cwd=cls.tmp, fixture_base_url=cls.base_url, fixture_name="01-clean",
            timeout=180,
        )
        cls.bodies = fs.get_request_bodies()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cleanup_repo(cls.tmp)

    def test_the_definition_is_not_sent(self):
        self.assertGreater(len(self.bodies), 0)
        self.assertFalse(any("errName: string" in b for b in self.bodies))

    def test_the_opt_out_is_reported(self):
        self.assertIn("[CONTEXT-GAP]", self.result.stdout, msg=self.result.stdout)
        self.assertIn("--no-context", self.result.stdout)
