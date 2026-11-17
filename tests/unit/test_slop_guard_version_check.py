"""scripts/check-slop-guard-version.sh, with PyPI stubbed by a file:// URL."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("SLOP_GUARD_CHECK_SCRIPT") or REPO / "scripts/check-slop-guard-version.sh")


def run(tmp_path: Path, vendor_version: str | None, pypi_body: str | None):
    vendor = tmp_path / "VENDOR.json"
    if vendor_version is not None:
        vendor.write_text(json.dumps({"version": vendor_version}))
    pypi = tmp_path / "pypi.json"
    if pypi_body is not None:
        pypi.write_text(pypi_body)
    env = dict(os.environ, SLOP_GUARD_PYPI_URL=f"file://{pypi}")
    return subprocess.run(["bash", str(SCRIPT), str(vendor)], capture_output=True, text=True, env=env)


def body(v: str) -> str:
    return json.dumps({"info": {"version": v}})


def test_equal_versions_need_no_update(tmp_path):
    r = run(tmp_path, "0.5.0", body("0.5.0"))
    assert r.returncode == 0 and "needs_update=false" in r.stdout


def test_newer_release_needs_update(tmp_path):
    r = run(tmp_path, "0.5.0", body("0.6.0"))
    assert r.returncode == 0 and "needs_update=true" in r.stdout


@pytest.mark.parametrize(
    "vendor, pypi",
    [("0.5.0", None), ("0.5.0", "not json"), ("0.5.0", "{}"), (None, body("0.5.0"))],
    ids=["pypi-unreachable", "pypi-garbage", "pypi-no-version", "vendor-missing"],
)
def test_unknown_version_fails_instead_of_reporting_current(tmp_path, vendor, pypi):
    r = run(tmp_path, vendor, pypi)
    assert r.returncode == 1, r.stdout
    assert "needs_update" not in r.stdout


def test_real_vendor_file_is_readable():
    r = subprocess.run(["jq", "-er", ".version", str(REPO / "dotfiles/claude/skills/writing-check/vendor/slop-guard/VENDOR.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "0.5.0"
