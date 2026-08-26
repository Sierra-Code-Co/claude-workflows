"""Auto-pause-after-N state file with fcntl.flock. Single context manager spans read-modify-write."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_STATE_PATH = Path(os.environ.get(
    "REVIEW_PLAN_V2_STATE_FILE",
    str(Path.home() / ".claude" / "review-plan-v2" / "auto-pause-state.json"),
))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_key(cwd: str | None = None) -> str:
    """`git rev-parse --git-common-dir` — same path for every worktree of one underlying repo."""
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=True, cwd=cwd,
    )
    return os.path.abspath(out.stdout.strip())


def current_branch(cwd: str | None = None) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True, cwd=cwd,
    )
    return out.stdout.strip()


class StateSession:
    def __init__(self, state: dict, key: str):
        self._state = state
        self._key = key
        entry = state.setdefault(key, {})
        self.consecutive_trivial: int = int(entry.get("consecutive_trivial_runs", 0))
        self.last_run_commits: list[str] = list(entry.get("last_run_commits", []))
        # Round-N finding memory (T048, #20). Hashes only — never message text;
        # FR-015 bars message bodies from persisted telemetry and this file sits
        # beside it.
        prior = entry.get("finding_history")
        self.finding_history: list[dict] = list(prior) if isinstance(prior, list) else []
        self.round_number: int = int(entry.get("round_number", 0)) + 1
        self._recorded = False
        self._holder_started_at = _now_iso()  # set at session start, not at record()

    def record(self, was_trivial: bool, head_commit: str | None = None) -> None:
        """Update the in-memory state. Persisted on context exit."""
        self.consecutive_trivial = self.consecutive_trivial + 1 if was_trivial else 0
        if head_commit:
            self.last_run_commits = (self.last_run_commits + [head_commit])[-10:]
        self._state[self._key] = {
            "consecutive_trivial_runs": self.consecutive_trivial,
            "last_run_commits": self.last_run_commits,
            # Written back explicitly. This dict REPLACES the entry, so any key
            # not listed here is silently dropped — which is how round memory
            # would have quietly reset on every run.
            "finding_history": self.finding_history,
            "round_number": self.round_number,
            "last_updated": _now_iso(),
            "holder_pid": os.getpid(),
            "holder_started_at": self._holder_started_at,
        }
        self._recorded = True

    def should_pause(self, threshold: int) -> bool:
        return self.consecutive_trivial >= threshold


@contextmanager
def state_session(repo_key_str: str, branch: str, state_path: Path | None = None) -> Iterator[StateSession]:
    """Hold fcntl.flock across the full review. Persists on clean exit."""
    path = state_path or DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    key = f"{repo_key_str}:{branch}"
    # O_CREAT, not exists()-then-write_text(). The old form created the file
    # OUTSIDE the lock, so two starters could interleave as:
    #
    #   A: exists() -> False
    #   B: exists() -> False
    #   A: write_text("{}"); lock; read {}; count=1; write; unlock
    #   B: write_text("{}")        <-- truncates the value A just committed
    #   B: lock; read {}; count=1; write
    #
    # Two records, counter 1. Exactly one increment lost — which is why the
    # symptom was always `19 != 20` and never 18: the window exists only at
    # creation. The flock was never the problem; the unlocked truncation ahead
    # of it was. O_CREAT creates only when missing and never truncates, so there
    # is nothing to lose, and an empty or partial file still parses to {} below.
    #
    # Filed as T011a "flaky test". It was never flaky. It reported a real lost
    # update, correctly, every time it lost the race — 9 times in 25 container
    # runs. The docstring's "Lock spans full session, so no race" was true of
    # the code the lock covered and false of the code that ran before it.
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    fd_owned_by_file = False
    try:
        # Non-blocking first, purely so a wait can be ANNOUNCED. The lock is
        # exclusive and spans the entire review, and the default path is ONE file
        # shared by every repo on the machine (keyed by repo:branch inside, but
        # locked as a whole). So a second run started while a first is in flight
        # blocks here — before the `broad pass:` line, after the gate-portfolio
        # line — and prints nothing for as long as the first review takes.
        #
        # Measured: two runs launched 3 minutes apart in different repos. The
        # second sat silent for 20+ minutes with no output, no child process, and
        # a live pid. Every diagnostic that a hang gets — is the process alive, is
        # it in a subprocess, is the network moving — said "fine", because it was
        # fine. It was queued. A tool that waits without saying so is
        # indistinguishable from a tool that has hung, and this one instructs its
        # operator that a run may legitimately take more than ten minutes, which
        # removes the only remaining signal.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # PermissionError alongside BlockingIOError, and NOT redundant: a contended
        # LOCK_NB raises EAGAIN on darwin and linux (measured on this host: errno 35,
        # BlockingIOError), but POSIX permits EACCES for the same condition, which
        # Python maps to PermissionError. On such a platform the narrower catch turns
        # a queue into a traceback — the failure mode this whole block exists to
        # remove. Listed here rather than left to be "cleaned up" as unreachable.
        except (BlockingIOError, PermissionError):
            # Deliberately does NOT name a holder. Every `holder_pid` in the file
            # is written by record() on a CLEAN EXIT, so the live holder has not
            # written anything yet and the pid on disk belongs to the previous
            # completed run. Naming it would be a plausible, checkable-looking
            # claim that is wrong exactly when it matters.
            print(
                f"WAITING: another review-plan-v2 run holds the shared state file "
                f"({path}). The lock spans a whole review, so this can be several "
                f"minutes — this is a queue, not a hang. Point "
                f"REVIEW_PLAN_V2_STATE_FILE at a per-repo path to run two reviews "
                f"at once.",
                file=sys.stderr, flush=True,
            )
            fcntl.flock(fd, fcntl.LOCK_EX)
        f = os.fdopen(fd, "r+", encoding="utf-8")  # f now owns fd
        fd_owned_by_file = True
        with f:
            try:
                state = json.load(f)
                if not isinstance(state, dict):
                    state = {}
            except json.JSONDecodeError:
                state = {}
            session = StateSession(state, key)
            try:
                yield session
            finally:
                if session._recorded:
                    f.seek(0)
                    f.truncate()
                    json.dump(state, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
            # fd closed by f.__exit__ on `with f:` exit — releases flock
    finally:
        if not fd_owned_by_file:
            try:
                os.close(fd)
            except OSError:
                pass
