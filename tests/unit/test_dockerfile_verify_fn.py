"""The Dockerfile's `verify()` is EXECUTED here, not read (T005d).

Review's sharpest finding on T005d: both failure branches of `verify()` had been
proven only by hand — three real `docker build` runs on 2026-08-16 showing
`DIGEST MISMATCH` and `REFUSING` and exit 1. That is a measurement, not a gate.
It does not run again tomorrow, it does not run in CI, and nothing notices when
someone edits the function.

So the function is extracted from the Dockerfile and run, in bash, against real
files. Extraction rather than a copy is the point: a copy is a second source of
truth that drifts silently, and the extraction failing loudly is itself the
signal that the Dockerfile changed shape.

No skips. `sha256sum` is coreutils and absent from a stock macOS, so a shim
delegating to `shasum -a 256` is put on PATH when needed — a skip here would be
the same "silently did not run" defect the whole spec exists to close.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: sha256 of b"hello\n", computed independently of the code under test.
HELLO_SHA = "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
WRONG_SHA = "0" * 64


def _verify_fn() -> str:
    """Lift `verify()` out of the Dockerfile and undo the line continuations."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    m = re.search(r"(verify\(\) \{.*?\n\s*\}; \\)", dockerfile, re.S)
    assert m, (
        "verify() could not be extracted from the Dockerfile. It was renamed, "
        "reshaped, or removed — do not relax this regex without checking which."
    )
    body = m.group(1)
    body = re.sub(r"\\\n\s*", " ", body)      # join continuations
    body = body.rstrip().removesuffix("\\").rstrip()
    assert "sha256sum -c" in body, "the extracted function no longer hashes anything"
    return body


@pytest.fixture()
def run_verify(tmp_path):
    """→ callable(digest, path) -> CompletedProcess, running the REAL function."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    env = dict(os.environ)
    if shutil.which("sha256sum") is None:
        # Stock macOS ships `shasum`, not `sha256sum`. Shim rather than skip.
        shim = shim_dir / "sha256sum"
        shim.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
        shim.chmod(0o755)
        env["PATH"] = f"{shim_dir}:{env['PATH']}"

    script = tmp_path / "run.sh"

    def _run(digest: str, target: pathlib.Path) -> subprocess.CompletedProcess:
        script.write_text(textwrap.dedent(f"""\
            set -eu
            {_verify_fn()}
            verify "$1" "$2"
        """))
        return subprocess.run(
            ["bash", str(script), digest, str(target)],
            capture_output=True, text=True, env=env, cwd=tmp_path,
        )

    return _run


@pytest.fixture()
def artifact(tmp_path) -> pathlib.Path:
    p = tmp_path / "artifact.tar.gz"
    p.write_bytes(b"hello\n")
    return p


def test_a_matching_digest_is_accepted(run_verify, artifact):
    """Anti-vacuous control. A `verify` that rejected everything would satisfy
    both failure tests below while making the image unbuildable."""
    result = run_verify(HELLO_SHA, artifact)
    assert result.returncode == 0, result.stderr


def test_a_wrong_digest_is_rejected(run_verify, artifact):
    result = run_verify(WRONG_SHA, artifact)
    assert result.returncode != 0
    assert "DIGEST MISMATCH" in result.stderr


def test_an_EMPTY_digest_is_refused_rather_than_skipped(run_verify, artifact):
    """The branch that needed its own guard.

    `sha256sum -c` on an empty hash is a FORMAT error, not a mismatch, so
    without the explicit `test -n` a `--build-arg YQ_SHA256_AMD64=` would turn
    verification off while the build log stayed byte-identical. That is the
    exact silent-degradation shape this portfolio exists to close, and it would
    have been reachable from the command line.
    """
    result = run_verify("", artifact)
    assert result.returncode != 0
    assert "REFUSING" in result.stderr


def test_a_missing_file_is_rejected(run_verify, tmp_path):
    """A download that never landed must not read as verified."""
    result = run_verify(HELLO_SHA, tmp_path / "never-downloaded.tar.gz")
    assert result.returncode != 0
