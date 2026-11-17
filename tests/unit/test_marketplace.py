"""The Claude Code plugin list published in the public mirror (public/.claude-plugin/).

The file only exists in the mirror, at its root, so every relative path in it is
resolved against this repo's root (where the manifest paths come from) and must
fall under a path that scripts/public-manifest.txt publishes.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# This suite also runs in the public mirror, where public/ has been overlaid at
# the root and no public/ folder exists. Internal path first, then the mirror's.
_MARKET_CANDIDATES = (
    REPO / "public/.claude-plugin/marketplace.json",  # internal repo
    REPO / ".claude-plugin/marketplace.json",  # public mirror root
)
MARKET = next((p for p in _MARKET_CANDIDATES if p.exists()), _MARKET_CANDIDATES[0])


def manifest_entries() -> list[str]:
    out = []
    for line in (REPO / "scripts/public-manifest.txt").read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            out.append(entry)
    return out


def problems(market: dict) -> list[str]:
    out = []
    published = manifest_entries()
    for key in ("name", "owner", "plugins"):
        if key not in market:
            out.append(f"missing {key}")
    if market.get("name", "").startswith(("claude-", "anthropic-")):
        out.append("reserved marketplace name")
    for p in market.get("plugins", []):
        if p.get("name", "").startswith(("claude-", "anthropic-")):
            out.append(f"reserved plugin name {p.get('name')}")
        if "version" in p:
            out.append(f"{p['name']}: has a version; we track commits (ADR-0013)")
        if p.get("source") != "./":
            out.append(f"{p['name']}: source must be ./")
        for s in p.get("skills", []):
            rel = s.removeprefix("./").rstrip("/")
            if ".." in Path(rel).parts:
                out.append(f"{s}: escapes the repo")
            if not (REPO / rel / "SKILL.md").is_file():
                out.append(f"{s}: no SKILL.md in this repo")
            if not any(rel == e.rstrip("/") or rel.startswith(e) for e in published if e.endswith("/")):
                out.append(f"{s}: not under a published manifest path")
    return out


def test_marketplace_is_valid_and_points_at_published_skills():
    market = json.loads(MARKET.read_text())
    assert problems(market) == []
    assert [p["name"] for p in market["plugins"]] == ["writing-check"]
    assert market["name"] == "sierra-code-co"


def test_checker_catches_bad_entries():
    bad = {
        "name": "claude-tools",
        "owner": {"name": "x"},
        "plugins": [
            {"name": "x", "source": "./", "version": "1.0.0", "skills": ["./private/skill", "./../escape"]},
        ],
    }
    found = problems(bad)
    assert "reserved marketplace name" in found
    assert any("has a version" in f for f in found)
    assert any("no SKILL.md" in f for f in found)
    assert any("not under a published manifest path" in f for f in found)
    assert any("escapes the repo" in f for f in found)
