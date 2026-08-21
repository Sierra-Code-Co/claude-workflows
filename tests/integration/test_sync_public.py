"""Failure proofs for scripts/sync-public.sh — the public-mirror leak gate.

Every test drives the real script via the SYNC_* env overrides against a
throwaway fixture repo, because the gate's whole job is refusing to publish:
a gate with no failing test is indistinguishable from no gate (see gates.yml).

Requires gitleaks on PATH (the script itself refuses to run without it, by
design); tests skip where it's absent rather than weakening the script.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sync-public.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks not installed"
)


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "sync-public tests")


@pytest.fixture()
def fixture(tmp_path):
    """A tiny source repo + pre-initialized mirror clone."""
    source = tmp_path / "source"
    _init_repo(source)
    (source / "keep.md").write_text("published content\n")
    (source / "sub").mkdir()
    tool = source / "sub" / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (source / "private.md").write_text("never published\n")
    (source / "public").mkdir()
    (source / "public" / "README.md").write_text("mirror readme\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "fixture")

    manifest = tmp_path / "manifest.txt"
    manifest.write_text("# fixture manifest\nkeep.md\nsub/\n")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("# fixture denylist\nci:acme-client\ncs:\\bAsh\\b\n")

    mirror = tmp_path / "mirror"
    _init_repo(mirror)

    env = os.environ.copy()
    env.update(
        SYNC_SOURCE_DIR=str(source),
        SYNC_MANIFEST=str(manifest),
        SYNC_DENYLIST=str(denylist),
        PUBLIC_MIRROR_DIR=str(mirror),
        PUBLIC_REMOTE=str(tmp_path / "nonexistent-remote.git"),
    )
    return type(
        "F", (), dict(source=source, manifest=manifest, denylist=denylist,
                      mirror=mirror, env=env)
    )


def run_sync(fx, *args):
    return subprocess.run(
        [str(SCRIPT), *args], env=fx.env, capture_output=True, text=True
    )


def mirror_commits(fx):
    out = subprocess.run(
        ["git", "-C", str(fx.mirror), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True,
    )
    return int(out.stdout) if out.returncode == 0 else 0


def test_denylist_hit_aborts_before_mirror_is_touched(fixture):
    (fixture.source / "keep.md").write_text("our client Acme-Client shipped\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 2
    assert "DENYLIST HIT" in result.stdout
    assert mirror_commits(fixture) == 0
    assert not (fixture.mirror / "keep.md").exists()


def test_malformed_denylist_pattern_fails_closed(fixture):
    fixture.denylist.write_text("ci:*broken(\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 2
    assert "failing closed" in result.stderr
    assert mirror_commits(fixture) == 0


def test_manifest_entry_escaping_repo_is_refused(fixture):
    outside = fixture.source.parent / "outside.txt"
    outside.write_text("outside the repo\n")
    fixture.manifest.write_text("../outside.txt\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 2
    assert "escapes the repo" in result.stderr
    assert mirror_commits(fixture) == 0


def test_dry_run_is_default_and_commits_nothing(fixture):
    result = run_sync(fixture)
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert mirror_commits(fixture) == 0


def test_clean_apply_publishes_allowlist_plus_overlay_only(fixture):
    result = run_sync(fixture, "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (fixture.mirror / "keep.md").exists()
    assert (fixture.mirror / "sub" / "tool.sh").exists()
    assert (fixture.mirror / "README.md").read_text() == "mirror readme\n"
    assert not (fixture.mirror / "private.md").exists()
    assert mirror_commits(fixture) == 1
    msg = subprocess.run(
        ["git", "-C", str(fixture.mirror), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert msg.startswith("sync: internal@")


def test_executable_bit_survives_into_mirror_git_index(fixture):
    run_sync(fixture, "--apply")
    entry = subprocess.run(
        ["git", "-C", str(fixture.mirror), "ls-files", "-s", "sub/tool.sh"],
        capture_output=True, text=True,
    ).stdout
    assert entry.startswith("100755"), entry


def test_dropping_a_manifest_path_removes_it_from_the_mirror(fixture):
    run_sync(fixture, "--apply")
    fixture.manifest.write_text("sub/\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 0
    assert not (fixture.mirror / "keep.md").exists()
    assert mirror_commits(fixture) == 2


def test_denylist_file_itself_is_never_staged_or_self_tripped(fixture):
    # A copy of the denylist inside an allowlisted dir contains the literal
    # pattern text ("acme-client"); if staged, it would trip its own gate AND
    # publish the very names the gate protects. It must simply not sync.
    scripts_dir = fixture.source / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "public-denylist.txt").write_text("ci:acme-client\n")
    fixture.manifest.write_text("keep.md\nscripts/\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (fixture.mirror / "scripts" / "public-denylist.txt").exists()


def test_dirty_worktree_is_labeled_in_the_sync_commit(fixture):
    (fixture.source / "keep.md").write_text("edited after last commit\n")
    result = run_sync(fixture, "--apply")
    assert result.returncode == 0
    msg = subprocess.run(
        ["git", "-C", str(fixture.mirror), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert msg.endswith("-dirty")
