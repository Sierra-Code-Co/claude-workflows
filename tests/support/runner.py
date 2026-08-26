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

# run_v2 reads the provider registry to wire env vars, so this module needs
# `review_plan_v2` importable in-process, not only on the subprocess's PYTHONPATH.
# pytest supplies it via pyproject's `pythonpath`; this makes a direct `python3
# tests/...` run work too, which is how the guarded modules under tests/unit run.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from review_plan_v2.providers import registry  # noqa: E402


@dataclass
class CmdResult:
    stdout: str
    stderr: str
    exit_code: int


def _unquote_diff_path(raw: str) -> str:
    """Undo git's C-style quoting of a path in a diff header.

    With `core.quotePath` on — the default — `git diff` renders a non-ASCII or
    control-character path as `"b/caf\\303\\251.ts"`, octal-escaped and wrapped in
    double quotes. The comparison below is against `git ls-files -z`, which emits
    the raw bytes, so a quoted header and an unquoted listing never match: the
    path reads as "added but not committed" and raises an assertion blaming the
    developer's global gitignore. That is the same unreproducible-on-any-other-
    machine failure the assertion's own message warns about, manufactured by the
    check written to explain it — for the second time in this function, the first
    being the whitespace split that `-z` fixed.

    `unicode_escape` decodes the octal escapes to latin-1 code points, so the
    bytes are recovered by re-encoding latin-1 before decoding as UTF-8.
    """
    if not (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2):
        return raw
    inner = raw[1:-1]
    try:
        return inner.encode("latin-1", "backslashreplace").decode(
            "unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        # Better the quoted form than a crash: the assertion below then reports a
        # mismatch naming the odd path, which is a diagnosable failure.
        return inner


def make_repo_from_diff(diff_path: Path) -> Path:
    """Initialize a temp git repo, apply the diff as a single commit on top of an empty base, return the repo path.

    The diff text is expected to be the standard `git diff` format. We reconstruct the
    "after" state by applying the diff to an empty tree (any context lines must already
    appear in the +/- markers; for our fixtures we use full-file additions where possible).

    For diffs that include context lines, the simpler approach is to bake the "before"
    files in advance — but for our MVP fixtures, we use diffs against an empty seed.

    A fixture repo must not consult the developer's global gitignore, and getting that
    wrong cost this repo three months of misdiagnosis. `git apply` writes every file in
    the patch to disk, but a plain `git add -A` SKIPS the ignored ones without a word and
    still exits 0, so the fixture commit silently contained a subset of its own fixture.
    On this machine `~/.gitignore_global` has a `lib/` line, which matches
    `src/lib/auth/session.ts` in 05-cascade-trigger.diff — the only high-risk-path file
    in that fixture. So the reviewed diff held one non-high-risk file, no chunk matched
    `src/lib/auth/**`, and the cascade legs were built and then correctly had nothing to
    run on. That surfaced as "the cascade never engages", was read as a wiring bug for
    months, and would have reproduced on no machine whose global ignore lacked `lib/`.

    Hence both of the below: `--force` to stage ignored paths, and a hard check that the
    committed tree really does contain every path the patch adds. The check is the part
    that matters — `--force` fixes today's pattern, and the assertion catches whatever
    pattern someone's global ignore has tomorrow.
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
    # Stage + commit any new files. --force so a developer's global gitignore cannot
    # decide which parts of a fixture the tests get to see.
    subprocess.run(["git", "add", "-A", "--force"], cwd=tmp, check=True)
    # --allow-empty, matching the `git apply --allow-empty` above. An empty fixture
    # diff is a deliberate case (the no-op-change tests), and without this the
    # commit exits 1 and `check=True` raises a CalledProcessError from the harness
    # — a fixture-construction crash reported as a test failure, which sends the
    # reader to the tool rather than to the fixture.
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "fixture diff"],
                   cwd=tmp, check=True)

    # Verify the commit contains every path the patch adds. Parsed from the `+++ b/...`
    # lines rather than from `git apply --numstat`, so it needs no second git invocation.
    added = set()
    for line in diff_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            added.add(_unquote_diff_path(line[4:].split("\t", 1)[0]).removeprefix("b/"))
    # `-z` and split on NUL, not `.split()` on whitespace. A tracked path
    # containing a space fragmented into two entries, so `added - tracked` found
    # the real path "missing" and raised the assertion below — which then blames a
    # global gitignore. That is the same inexplicable-machine-specific failure the
    # message warns about, manufactured by the check meant to explain it. `git
    # ls-files` also QUOTES such paths without `-z` (core.quotePath), so
    # splitlines() alone would not be enough.
    # encoding pinned: `text=True` alone decodes with the locale's preferred encoding,
    # so a non-ASCII fixture path would decode differently here than in
    # `_unquote_diff_path`, which hardcodes UTF-8. The two sides of `added - tracked`
    # have to agree byte-for-byte or the mismatch is reported as a gitignore problem —
    # again the failure this check exists to explain, manufactured by the check.
    tracked = set(subprocess.run(
        ["git", "ls-files", "-z"], cwd=tmp, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.split("\0")) - {""}
    missing = sorted(added - tracked)
    if missing:
        raise AssertionError(
            f"fixture {diff_path.name} applied but these paths are not in the commit: "
            f"{missing}. Almost certainly a global gitignore is matching them — check "
            f"`git check-ignore -v <path>` and `git config --get core.excludesFile`. "
            f"A fixture repo missing part of its own fixture produces a green or "
            f"inexplicably-red test that reproduces on no other machine."
        )
    return tmp


def run_v2(*args: str, cwd: Path, fixture_base_url: str | None = None,
           fixture_name: str = "01-clean", env_extra: dict | None = None,
           timeout: float = 30.0) -> CmdResult:
    """Invoke `python3 -m review_plan_v2 <args>` with fixture-server env wiring."""
    env = os.environ.copy()
    # `os.pathsep.join(filter(None, ...))`, not `a + ":" + b`. With PYTHONPATH
    # unset the literal form appended a trailing separator, and an empty
    # PYTHONPATH entry means the CURRENT WORKING DIRECTORY — so every subprocess
    # got its cwd on sys.path, which for these tests is a fixture repo. A stray
    # module there would shadow a real one and the failure would look like a bug
    # in the tool. `:` is also hardcoded; os.pathsep is `;` on Windows.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SCRIPTS_DIR), env.get("PYTHONPATH")) if p
    )
    # Point EVERY provider at the fixture server and give each a key, rather than
    # only the two that happened to be wired when this was written (deepseek +
    # anthropic). Two reasons:
    #
    #   1. The broad-pass provider is configurable and its default has already
    #      moved once. When it moved off deepseek, 15 integration tests failed
    #      with "[DEAD-LEG] broad provider has no API key" — the tool was right
    #      and the harness was stale. Wiring by provider list rather than by
    #      literal means the next flip needs no change here.
    #   2. A provider with no key is SKIPPED, not failed, so an unwired cascade
    #      leg makes its tests pass by not running. test_no_cascade_flag_disables
    #      _frontier_cascade could not tell "disabled by the flag" from "never
    #      configured".
    #
    # Both var lists come from the registry, not from literals here. They were
    # literals until 2026-08-25 — directly under reason 1, which says not to write
    # them as literals. A provider added to the registry and forgotten here has no
    # key, and by reason 2 that means its tests pass without running.
    if fixture_base_url:
        for tag in registry.ALL_TAGS:
            env[registry.BASE_ENV[tag]] = fixture_base_url
    # Keys are FORCED, not defaulted, whenever a fixture server is in play. With
    # setdefault, a developer who has real provider keys exported — the normal state
    # for anyone who also runs this tool for real — sent those keys to a local HTTP
    # server in an Authorization header, and the fixture server logs requests. Test
    # runs must not be able to leak a live credential into a log file. Without a
    # fixture server the process talks to real endpoints, so there the ambient key is
    # the point and setdefault is correct.
    for tag in registry.ALL_TAGS:
        for var in registry.KEY_ENV[tag]:
            if fixture_base_url:
                env[var] = "test-key"
            else:
                env.setdefault(var, "test-key")
    # PIN the broad provider, do not inherit it. `env` is a copy of the parent
    # environment, and REVIEW_PLAN_V2_BROAD_PROVIDER is a documented operator
    # override that beats every config file — so an operator who exports it for
    # their own runs silently re-pointed the broad pass inside these tests, and
    # the several assertions written against `registry.DEFAULT_BROAD` then compared
    # two different providers. A test whose verdict depends on the developer's
    # shell is the same class as the keys forced above, and it fails on one machine
    # for a reason that is invisible in the diff. Forced rather than setdefault for
    # exactly that reason. A test that wants a different provider passes it through
    # `env_extra`, which is applied after this and still wins.
    env["REVIEW_PLAN_V2_BROAD_PROVIDER"] = registry.DEFAULT_BROAD
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
