#!/usr/bin/env python3
"""Build one Microsoft 365 Copilot upload zip per library skill.

    python3 scripts/build-copilot-zips.py           # write dist/copilot/<skill>.zip
    python3 scripts/build-copilot-zips.py --check   # exit 1 if a committed zip is stale

Copilot's Upload skill dialog takes a .zip with SKILL.md at the zip root (no
enclosing folder). The zip is built from the skill folder in this repo, with
sorted members, fixed timestamps and fixed modes, so the same source always
gives the same bytes. The committed zip is therefore checkable: --check (and
tests/unit/test_copilot_zip.py) rebuild it in memory and compare, which keeps
the download from becoming a second copy that drifts.

Exit 0 written or current, 1 stale (--check), 2 error (no skills, bad layout).
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "dotfiles/claude/skills"
OUT = REPO / "dist/copilot"
EPOCH = (1980, 1, 1, 0, 0, 0)
# Per-skill folders left out of the Copilot zip, with the reason. Empty until
# the browser upload test shows something cannot run in Copilot's sandbox.
EXCLUDE: dict[str, tuple[str, ...]] = {}
SKIP_NAMES = {".DS_Store", "__pycache__"}


def members(skill: Path) -> list[Path]:
    excluded = EXCLUDE.get(skill.name, ())
    out = []
    for p in sorted(skill.rglob("*")):
        rel = p.relative_to(skill)
        if p.is_dir() or any(part in SKIP_NAMES for part in rel.parts) or p.suffix == ".pyc":
            continue
        if any(rel.as_posix().startswith(e.rstrip("/") + "/") for e in excluded):
            continue
        out.append(p)
    return out


def build(skill: Path) -> bytes:
    if not (skill / "SKILL.md").is_file():
        raise SystemExit(f"build-copilot-zips: {skill} has no SKILL.md")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in members(skill):
            info = zipfile.ZipInfo(p.relative_to(skill).as_posix(), EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if p.suffix in (".sh", ".py", ".pyz") else 0o644
            info.external_attr = mode << 16
            z.writestr(info, p.read_bytes())
    return buf.getvalue()


def skills() -> list[Path]:
    found = sorted(d for d in SKILLS.iterdir() if (d / "SKILL.md").is_file()) if SKILLS.is_dir() else []
    if not found:
        print(f"build-copilot-zips: no skills under {SKILLS}", file=sys.stderr)
        sys.exit(2)
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare committed zips with a fresh build")
    a = ap.parse_args()
    stale = []
    for skill in skills():
        target = OUT / f"{skill.name}.zip"
        data = build(skill)
        if a.check:
            if not target.is_file() or target.read_bytes() != data:
                stale.append(target.relative_to(REPO).as_posix())
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print(f"build-copilot-zips: wrote {target.relative_to(REPO)} ({len(data)} bytes)")
    if stale:
        print("build-copilot-zips: stale, run scripts/build-copilot-zips.py: " + ", ".join(stale), file=sys.stderr)
        sys.exit(1)
    if a.check:
        print("build-copilot-zips: all zips current")


if __name__ == "__main__":
    main()
