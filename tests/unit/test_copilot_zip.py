"""The Copilot upload zip: SKILL.md at the root, within limits, and current.

Limits are Microsoft's Agent Builder limits (50 MB zip, 25 MB per file, 350
files, folder depth 3); the personal-upload limits are unpublished, so these
are the design ceiling (spec 004 research R5).
"""
from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ZIP = REPO / "dist/copilot/writing-check.zip"
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load_builder():
    spec = importlib.util.spec_from_file_location("bcz", REPO / "scripts/build-copilot-zips.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def frontmatter(text: str) -> dict:
    """The YAML frontmatter, parsed (so `description: ""` decodes to an empty string)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), "frontmatter must be a YAML mapping"
    return data


def frontmatter_problems(text: str, folder: str) -> list[str]:
    fm = frontmatter(text)
    out = [f"non-standard key {k}" for k in fm if k not in ALLOWED_KEYS]
    name, desc = fm.get("name"), fm.get("description")
    if not isinstance(name, str):
        out.append(f"name is not a string: {name!r}")
        name = ""
    if not isinstance(desc, str):
        out.append(f"description is not a string: {desc!r}")
        desc = ""
    if not (1 <= len(name) <= 64 and NAME_RE.match(name)):
        out.append(f"bad name {name!r}")
    if name != folder:
        out.append(f"name {name!r} does not match folder {folder!r}")
    if name.startswith(("claude-", "anthropic-")):
        out.append("reserved name prefix")
    if not 1 <= len(desc) <= 1024:
        out.append(f"description length {len(desc)}")
    if "compatibility" in fm and len(str(fm["compatibility"])) > 500:
        out.append("compatibility over 500 chars")
    if len(text) >= 20_000 or text.count("\n") >= 500:
        out.append("SKILL.md over 20,000 chars or 500 lines")
    return out


def test_skill_md_is_at_the_zip_root():
    with zipfile.ZipFile(ZIP) as z:
        assert "SKILL.md" in z.namelist()


def test_zip_is_within_limits():
    with zipfile.ZipFile(ZIP) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        assert len(infos) < 350
        assert all(i.file_size < 25 * 2**20 for i in infos)
        assert all(i.filename.count("/") <= 2 for i in infos), [i.filename for i in infos if i.filename.count("/") > 2]
    assert ZIP.stat().st_size < 50 * 2**20


def test_frontmatter_meets_the_open_standard():
    with zipfile.ZipFile(ZIP) as z:
        text = z.read("SKILL.md").decode()
    assert frontmatter_problems(text, "writing-check") == []


@pytest.mark.parametrize(
    "bad, expect",
    [
        ("name: Writing_Check", "bad name"),
        ("name: claude-writing", "reserved"),
        ("when_to_use: always", "non-standard key"),
        ('description: ""', "description length 0"),
    ],
)
def test_frontmatter_check_catches_bad_input(bad, expect):
    text = (REPO / "dotfiles/claude/skills/writing-check/SKILL.md").read_text()
    key = bad.split(":")[0]
    if key in ("name", "description"):
        text = re.sub(rf"^{key}: .*$", lambda _m: bad, text, count=1, flags=re.M)
        folder = bad.split(": ")[1] if key == "name" else "writing-check"
    else:
        text = text.replace("\n---\n", f"\n{bad}\n---\n", 1)
        folder = "writing-check"
    assert any(expect in p for p in frontmatter_problems(text, folder))


def test_committed_zip_equals_a_fresh_build():
    builder = load_builder()
    fresh = builder.build(REPO / "dotfiles/claude/skills/writing-check")
    assert ZIP.read_bytes() == fresh, "stale: run python3 scripts/build-copilot-zips.py"


def test_stale_check_fails_after_a_source_change(tmp_path, monkeypatch):
    """Principle II: copy the skill, change one byte, and the build must differ."""
    import shutil

    builder = load_builder()
    copy = tmp_path / "writing-check"
    shutil.copytree(REPO / "dotfiles/claude/skills/writing-check", copy)
    (copy / "banned-phrases.txt").write_text((copy / "banned-phrases.txt").read_text() + "\\bextra\\b\n")
    assert builder.build(copy) != ZIP.read_bytes()


def test_zip_scripts_keep_their_execute_bit():
    with zipfile.ZipFile(ZIP) as z:
        mode = z.getinfo("scripts/prose-check.sh").external_attr >> 16
    assert mode & 0o111
