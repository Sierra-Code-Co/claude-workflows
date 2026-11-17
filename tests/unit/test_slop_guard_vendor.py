"""The packed slop-guard is upstream's wheel, unmodified, plus a declared overlay.

Constitution Principle VI: every vendored file carries provenance and is hashed
against upstream. The wheel's own RECORD lists a sha256 for every file it ships;
this test re-checks each packed file against it, offline. SLOP_GUARD_VENDOR_DIR
lets a scratch copy stand in so the check can be shown failing.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VENDOR = Path(os.environ.get("SLOP_GUARD_VENDOR_DIR") or REPO / "dotfiles/claude/skills/writing-check/vendor/slop-guard")
PYZ = VENDOR / "slop-guard.pyz"


def meta() -> dict:
    return json.loads((VENDOR / "VENDOR.json").read_text())


def problems_in(pyz: Path, overlay: list[str]) -> list[str]:
    out = []
    with zipfile.ZipFile(pyz) as z:
        names = set(z.namelist())
        records = [n for n in names if n.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            return [f"expected one RECORD, found {records}"]
        listed = set()
        for row in csv.reader(io.StringIO(z.read(records[0]).decode())):
            path, digest = row[0], row[1]
            listed.add(path)
            if path not in names:
                out.append(f"missing upstream file {path}")
                continue
            if not digest:  # RECORD does not hash itself
                continue
            algo, want = digest.split("=", 1)
            got = base64.urlsafe_b64encode(hashlib.new(algo, z.read(path)).digest()).rstrip(b"=").decode()
            if got != want:
                out.append(f"modified upstream file {path}")
        extra = names - listed - set(overlay)
        out += [f"undeclared file {n}" for n in sorted(extra)]
        out += [f"declared overlay missing {n}" for n in overlay if n not in names]
    return out


def test_vendor_json_records_provenance():
    m = meta()
    assert m["package"] == "slop-guard" and m["license"] == "MIT"
    assert len(m["wheel_sha256"]) == 64 and m["version"]
    assert m["overlay"] == ["__main__.py", "typing_extensions.py"]


def test_pyz_hash_matches_vendor_json():
    assert hashlib.sha256(PYZ.read_bytes()).hexdigest() == meta()["pyz_sha256"]


def test_every_upstream_file_is_unmodified_and_only_overlay_is_added():
    assert problems_in(PYZ, meta()["overlay"]) == []


def test_tampering_is_detected(tmp_path):
    """Principle II: rewrite one upstream file and the check must name it."""
    bad = tmp_path / "bad.pyz"
    with zipfile.ZipFile(PYZ) as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "slop_guard/models.py":
                data = data.replace(b"from typing_extensions import TypedDict", b"from typing import TypedDict")
            dst.writestr(info, data)
        dst.writestr("sneaky.py", "")
    found = problems_in(bad, meta()["overlay"])
    assert "modified upstream file slop_guard/models.py" in found
    assert "undeclared file sneaky.py" in found


def test_licence_is_upstreams_and_kept():
    text = (VENDOR / "LICENSE").read_text()
    assert text.startswith("MIT License") and "Copyright (c) 2026 Eric W. Tramel" in text
    with zipfile.ZipFile(PYZ) as z:
        inner = [n for n in z.namelist() if n.endswith("dist-info/licenses/LICENSE")]
        assert inner and z.read(inner[0]).decode() == text


def python311() -> str:
    """An interpreter that can run the pack (3.11+); the repo itself supports 3.10."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for name in ("python3.14", "python3.13", "python3.12", "python3.11"):
        found = shutil.which(name)
        if found:
            return found
    pytest.skip("no Python 3.11+ available to run the packed slop-guard")


def test_pyz_runs_with_nothing_installed_and_reports_its_version():
    # -I drops user site-packages and -S drops site-packages entirely, so an
    # undeclared dependency installed in the test interpreter cannot mask a gap.
    r = subprocess.run([python311(), "-I", "-S", str(PYZ), "--version"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == meta()["version"]
