"""run-all.sh's own control flow: the UNPROVEN protocol and the coverage gate.

Both were verified by hand when written, and by hand is exactly how a control
path stops being verified. These drive the real script against synthetic proof
directories, so the behaviour is pinned rather than remembered.

The two properties that matter, and they pull in opposite directions:

  * an UNPROVEN result must FAIL a run that has not acknowledged it, because
    "could not run" and "passed" printing the same thing is the single failure
    this suite exists to prevent;
  * an acknowledged UNPROVEN must still be REPORTED on a green run, because an
    exemption visible only when something else breaks is an exemption nobody
    reads.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ALL = REPO_ROOT / "tests" / "proofs" / "run-all.sh"

PASS = "#!/usr/bin/env bash\necho ok\nexit 0\n"
UNPROVEN = "#!/usr/bin/env bash\necho 'UNPROVEN: no key'\nexit 3\n"
FAILING = "#!/usr/bin/env bash\necho 'FAIL: seeded violation not detected'\nexit 1\n"

# A shape validator that always agrees, so these tests exercise the RUNNER
# rather than the coverage check. The one test that cares about coverage
# supplies a failing stub instead.
SHAPES_OK = "#!/usr/bin/env python3\nprint('  ok   stub: 1/1')\n"
SHAPES_BAD = (
    "#!/usr/bin/env python3\nimport sys\n"
    "print('FAIL: stub coverage incomplete')\nsys.exit(1)\n"
)


def _proof_dir(tmp_path: Path, proofs: dict[str, str], shapes: str = SHAPES_OK) -> Path:
    d = tmp_path / "proofs"
    d.mkdir()
    (d / "run-all.sh").write_text(RUN_ALL.read_text())
    (d / "run-all.sh").chmod(0o755)
    (d / "derive_shapes.py").write_text(shapes)
    for name, body in proofs.items():
        p = d / f"{name}.sh"
        p.write_text(body)
        p.chmod(0o755)
    return d


def _run(proof_dir: Path, **env) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.pop("RPV2_UNPROVEN_OK", None)
    e.update(env)
    return subprocess.run(
        ["bash", str(proof_dir / "run-all.sh")],
        capture_output=True, text=True, check=False, env=e, timeout=120,
    )


def test_all_passing_is_green(tmp_path):
    """Anti-vacuous control. Without it, "always exit 1" passes every test here."""
    r = _run(_proof_dir(tmp_path, {"a": PASS, "b": PASS}))
    assert r.returncode == 0, r.stdout
    assert "2 ok, 0 failed, 0 unproven" in r.stdout


def test_an_unacknowledged_unproven_fails_the_run(tmp_path):
    r = _run(_proof_dir(tmp_path, {"a": PASS, "live": UNPROVEN}))
    assert r.returncode == 1, r.stdout
    assert "not acknowledged" in r.stdout
    assert "live" in r.stdout


def test_an_acknowledged_unproven_passes_but_is_reported(tmp_path):
    r = _run(_proof_dir(tmp_path, {"a": PASS, "live": UNPROVEN}),
             RPV2_UNPROVEN_OK="live")
    assert r.returncode == 0, r.stdout
    assert "1 unproven" in r.stdout
    assert "NOT PROVEN this run" in r.stdout, (
        "an acknowledged gap must still be printed on a GREEN run, or the "
        "acknowledgement silently becomes coverage"
    )


def test_acknowledging_one_proof_does_not_cover_another(tmp_path):
    """The reason the acknowledgement is per-proof rather than a boolean.

    A blanket allow-unproven flag would cover the next gate that quietly stops
    working, which is the thing this suite must never make easy.
    """
    r = _run(_proof_dir(tmp_path, {"live": UNPROVEN, "other": UNPROVEN}),
             RPV2_UNPROVEN_OK="live")
    assert r.returncode == 1, r.stdout
    assert "other" in r.stdout


def test_a_genuine_failure_is_not_absolved_by_acknowledgement(tmp_path):
    """Exit 1 is not exit 3. Naming a proof must not mute a real red result."""
    r = _run(_proof_dir(tmp_path, {"live": FAILING}), RPV2_UNPROVEN_OK="live")
    assert r.returncode == 1, r.stdout
    assert "FAILED" in r.stdout


def test_whitespace_in_the_acknowledgement_list_is_tolerated(tmp_path):
    r = _run(_proof_dir(tmp_path, {"live": UNPROVEN, "b": PASS}),
             RPV2_UNPROVEN_OK="b, live")
    assert r.returncode == 0, r.stdout


def test_failing_shape_coverage_blocks_before_any_proof_runs(tmp_path):
    """The ordering is the whole point of T037.

    A proof that goes red proves the gate CAN fail; it says nothing about
    whether it fails on every shape the gate claims. Crediting a red result
    before checking coverage is how a fixture sat at eleven shapes with a
    load-bearing constraint unexercised while its proof passed every run.
    """
    r = _run(_proof_dir(tmp_path, {"a": PASS}, shapes=SHAPES_BAD))
    assert r.returncode == 1, r.stdout
    assert "shape coverage is incomplete" in r.stdout
    assert "running 1 failure proof" not in r.stdout, (
        "proofs ran despite incomplete coverage — their results must not be "
        "credited at all"
    )


def test_an_empty_proof_directory_is_not_success(tmp_path):
    r = _run(_proof_dir(tmp_path, {}))
    assert r.returncode == 1, r.stdout
    assert "no failure proofs registered" in r.stdout


def test_a_non_executable_proof_is_named_not_skipped(tmp_path):
    d = _proof_dir(tmp_path, {"a": PASS})
    dud = d / "half-written.sh"
    dud.write_text(PASS)
    dud.chmod(0o644)
    r = _run(d)
    assert r.returncode == 1, r.stdout
    assert "half-written.sh" in r.stdout


@pytest.mark.parametrize("code,expected_word", [(3, "UNPROVEN"), (1, "FAILED"), (2, "FAILED")])
def test_exit_codes_map_to_distinct_verdicts(tmp_path, code, expected_word):
    """Only 3 means UNPROVEN. An analyzer crashing with 2 must not be absolved."""
    body = f"#!/usr/bin/env bash\nexit {code}\n"
    r = _run(_proof_dir(tmp_path, {"p": body}))
    assert expected_word in r.stdout, r.stdout
