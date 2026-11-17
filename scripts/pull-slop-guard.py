#!/usr/bin/env python3
"""Rebuild the packed slop-guard inside the writing-check skill from a pinned PyPI wheel.

    python3 scripts/pull-slop-guard.py --version 0.5.0 --sha256 <wheel sha256>
    python3 scripts/pull-slop-guard.py --version 0.5.0 --sha256 <h> --wheel local.whl   # offline

Bumping slop-guard is a deliberate step: run this with the new pin, run the
tests (tests/unit/test_slop_guard_vendor.py and the phrase-list coverage test
will name any new upstream words that need a decision), then open a normal PR.
Nothing updates itself.

Constitution Principle VI (Pristine Upstream): every wheel member goes into the
zipapp byte-for-byte, including its dist-info (licence, METADATA so the version
lookup works, and RECORD so a test can re-verify every file). Local behaviour is
two OVERLAY files at the zip root, never an edit:

  typing_extensions.py  slop_guard/models.py imports TypedDict from
                        typing_extensions, a third-party package; the stdlib
                        typing module has had it since 3.8, so the shim
                        re-exports it and the pack runs with nothing installed.
  __main__.py           runs the `sg` command-line entry point
                        (slop_guard.apps.cli:main). The wheel's own
                        slop_guard/__main__.py starts the MCP server, which
                        needs the `mcp` package, so it is never used.

Exit 0 written, 2 on any error (hash mismatch, download failure, bad args).
Nothing is written unless every step succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEST = REPO / "dotfiles/claude/skills/writing-check/vendor/slop-guard"
EPOCH = (1980, 1, 1, 0, 0, 0)
OVERLAY = {
    "typing_extensions.py": (
        "# Overlay, not upstream: see writing-check/vendor/slop-guard/README.md.\n"
        "# slop_guard/models.py needs only TypedDict, which is in the stdlib.\n"
        "from typing import TypedDict  # noqa: F401\n"
    ),
    "__main__.py": (
        "# Overlay, not upstream: runs the `sg` CLI (slop_guard.apps.cli:main).\n"
        "import sys\n"
        "from slop_guard.apps.cli import main\n"
        "sys.exit(main())\n"
    ),
}


def fail(msg: str) -> None:
    print(f"pull-slop-guard: {msg}", file=sys.stderr)
    sys.exit(2)


def wheel_url(version: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/slop-guard/{version}/json", timeout=30) as r:
        data = json.load(r)
    for u in data["urls"]:
        if u["packagetype"] == "bdist_wheel":
            return u["url"]
    fail(f"no wheel published for slop-guard {version}")
    return ""  # unreachable


def entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def build_pyz(wheel_bytes: bytes) -> tuple[bytes, bytes]:
    """Return (pyz bytes, upstream LICENSE bytes)."""
    out = io.BytesIO()
    license_bytes = b""
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as w:
        names = sorted(w.namelist())
        clash = set(names) & set(OVERLAY)
        if clash:
            fail(f"overlay would shadow upstream files: {sorted(clash)}")
        with zipfile.ZipFile(out, "w") as z:
            for n in names:
                data = w.read(n)
                z.writestr(entry(n), data)
                if n.endswith(".dist-info/licenses/LICENSE"):
                    license_bytes = data
            for n in sorted(OVERLAY):
                z.writestr(entry(n), OVERLAY[n])
    if not license_bytes:
        fail("wheel carries no LICENSE; refusing to vendor without it")
    return b"#!/usr/bin/env python3\n" + out.getvalue(), license_bytes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--sha256", required=True, help="expected sha256 of the wheel (from PyPI)")
    ap.add_argument("--wheel", help="use a local wheel instead of downloading")
    ap.add_argument("--dest", default=str(DEST))
    a = ap.parse_args()

    try:
        if a.wheel:
            url = f"file:{Path(a.wheel).name}"
            wheel = Path(a.wheel).read_bytes()
        else:
            url = wheel_url(a.version)
            with urllib.request.urlopen(url, timeout=60) as r:
                wheel = r.read()
    except OSError as e:
        fail(f"could not get the wheel: {e}")
    got = hashlib.sha256(wheel).hexdigest()
    if got != a.sha256.lower():
        fail(f"wheel sha256 {got} does not match the pin {a.sha256}")

    pyz, license_bytes = build_pyz(wheel)
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "slop-guard.pyz").write_bytes(pyz)
    (dest / "LICENSE").write_bytes(license_bytes)
    vendor = {
        "package": "slop-guard",
        "version": a.version,
        "upstream": "https://github.com/eric-tramel/slop-guard",
        "license": "MIT",
        "wheel_url": url,
        "wheel_sha256": got,
        "pyz_sha256": hashlib.sha256(pyz).hexdigest(),
        "overlay": sorted(OVERLAY),
        "python_requires": ">=3.11",
    }
    (dest / "VENDOR.json").write_text(json.dumps(vendor, indent=2) + "\n")
    print(f"pull-slop-guard: wrote slop-guard {a.version} ({len(pyz)} bytes) to {dest}")


if __name__ == "__main__":
    main()
