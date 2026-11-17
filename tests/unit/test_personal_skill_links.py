"""new-machine.sh links each personal skill in dotfiles/claude/skills/ into ~/.claude/skills/.

Runs the real script with HOME pointed at a temp dir. NEW_MACHINE_SCRIPT lets a
scratch copy of the script stand in, so a guard can be broken there to watch
these tests go red without touching the real file.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("NEW_MACHINE_SCRIPT") or REPO / "scripts/new-machine.sh")
SKILL_SRC = REPO / "dotfiles/claude/skills/writing-check"


def run(home: Path):
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)


def test_creates_symlink_into_repo(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    link = tmp_path / ".claude/skills/writing-check"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == SKILL_SRC
    assert (link / "scripts/prose-check.sh").exists()


def test_second_run_changes_nothing(tmp_path):
    run(tmp_path)
    before = sorted(p.name for p in (tmp_path / ".claude/skills").iterdir())
    r = run(tmp_path)
    assert r.returncode == 0
    assert "writing-check already symlinked" in r.stdout
    assert sorted(p.name for p in (tmp_path / ".claude/skills").iterdir()) == before


def test_real_folder_is_backed_up_then_linked(tmp_path):
    real = tmp_path / ".claude/skills/writing-check"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("old copy\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert real.is_symlink()
    assert (tmp_path / ".claude/skill-backups/writing-check.bak/SKILL.md").read_text() == "old copy\n"
    # nothing but the link may sit in the skills folder, or the backup loads as a skill
    assert sorted(p.name for p in (tmp_path / ".claude/skills").iterdir()) == ["writing-check"]


def test_foreign_symlink_is_left_and_reported(tmp_path):
    skills = tmp_path / ".claude/skills"
    skills.mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (skills / "writing-check").symlink_to(other)
    r = run(tmp_path)
    assert r.returncode == 1
    assert Path(os.readlink(skills / "writing-check")) == other
    assert "not this repo" in r.stderr
