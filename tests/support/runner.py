"""Helpers to invoke the orchestrator as a subprocess against the fixture server."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


@dataclass
class CmdResult:
    stdout: str
    stderr: str
    exit_code: int


def make_repo_from_diff(diff_path: Path) -> Path:
    """Initialize a temp git repo, apply the diff as a single commit on top of an empty base, return the repo path.

    The diff text is expected to be the standard `git diff` format. We reconstruct the
    "after" state by applying the diff to an empty tree (any context lines must already
    appear in the +/- markers; for our fixtures we use full-file additions where possible).

    For diffs that include context lines, the simpler approach is to bake the "before"
    files in advance — but for our MVP fixtures, we use diffs against an empty seed.
    """
    tmp = Path(tempfile.mkdtemp(prefix="rpv2-test-repo-"))
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
    # Empty seed commit
    (tmp / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp, check=True)
    # Branch off
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=tmp, check=True)
    # Apply the diff
    subprocess.run(["git", "apply", "--allow-empty", str(diff_path)], cwd=tmp, check=True)
    # Stage + commit any new files
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture diff"], cwd=tmp, check=True)
    return tmp


def run_v2(*args: str, cwd: Path, fixture_base_url: str | None = None,
           fixture_name: str = "01-clean", env_extra: dict | None = None,
           timeout: float = 30.0) -> CmdResult:
    """Invoke `python3 -m review_plan_v2 <args>` with fixture-server env wiring."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPTS_DIR) + ":" + env.get("PYTHONPATH", "")
    if fixture_base_url:
        env["DEEPSEEK_API_BASE"] = fixture_base_url
        env["ANTHROPIC_API_BASE"] = fixture_base_url
    env.setdefault("DEEPSEEK_API_KEY", "test-key")
    env.setdefault("ANTHROPIC_API_KEY", "test-key")
    # Isolate state file per test run
    env.setdefault("REVIEW_PLAN_V2_STATE_FILE", str(cwd / ".rpv2-state.json"))
    env.setdefault("REVIEW_PLAN_V2_LOG_DIR", str(cwd / ".rpv2-logs"))
    if env_extra:
        env.update(env_extra)

    # NOTE: header injection for fixture selection is done via env to inner provider HTTP
    # since urllib doesn't pick headers from env. We pass it as a request header by
    # patching the providers — for now, the fixture server falls back to the file at
    # FIXTURES/<fixture_name>/<provider>.json using the value of REVIEW_PLAN_V2_TEST_FIXTURE.
    env["REVIEW_PLAN_V2_TEST_FIXTURE"] = fixture_name

    proc = subprocess.run(
        [sys.executable, "-m", "review_plan_v2", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
    )
    return CmdResult(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def cleanup_repo(repo_path: Path) -> None:
    if repo_path.exists() and "rpv2-test-repo-" in repo_path.name:
        shutil.rmtree(repo_path, ignore_errors=True)
