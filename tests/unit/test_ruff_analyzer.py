"""The ruff analyzer's output mapping (T005e).

The failure proof shows the gate CAN go red. It says nothing about whether a
finding arrives with the right file, line, severity or message — and a finding
that reports the wrong line is worse than none, because it sends the reader to
code that is fine.

Severity is derived rather than reported: ruff has no severity field. The
mapping is the judgment call in this module, so it is what these tests pin.
"""
from __future__ import annotations

import json

import pytest
from review_plan_v2.analyzers.ruff import RuffAnalyzer
from review_plan_v2.types import FileChange


def _issue(code="F401", filename="scripts/mod.py", row=3, end_row=3,
           message="`json` imported but unused"):
    return {
        "code": code,
        "filename": filename,
        "message": message,
        "location": {"row": row, "column": 1},
        "end_location": {"row": end_row, "column": 12},
    }


def _parse(issues):
    return RuffAnalyzer().parse_output(json.dumps(issues), "", [])


def test_a_finding_carries_file_line_and_message():
    (finding,) = _parse([_issue()])
    assert finding.file == "scripts/mod.py"
    assert finding.line == 3
    assert "F401" in finding.message
    assert "imported but unused" in finding.message
    assert finding.sources == ["ruff"]


def test_a_single_line_issue_reports_no_line_end():
    """`line_end == line` is noise in the renderer, which prints a range."""
    (finding,) = _parse([_issue(row=7, end_row=7)])
    assert finding.line_end is None


def test_a_multi_line_issue_keeps_its_range():
    (finding,) = _parse([_issue(row=7, end_row=9)])
    assert finding.line_end == 9


@pytest.mark.parametrize("code, severity", [
    ("F401", "actionable"),   # unused import — the rule that found 3 live ones
    ("F841", "actionable"),   # unused local — found a vacuous security test
    ("F821", "actionable"),   # undefined name
    ("E902", "actionable"),   # IO/syntax error
    ("E402", "nit"),          # import placement — real, not urgent
    ("W291", "nit"),          # trailing whitespace
    # NOT a rule id. Ruff reports an unparseable file as `invalid-syntax`, with
    # no numeric code, so every prefix branch missed it and the most severe
    # thing ruff can say was classified as a style nit. Shipped in T005e; found
    # in Phase 6 when a deliberately broken file failed to trigger the
    # deterministic short-circuit. Derived from ruff's real JSON output, not
    # from the code scheme I had in mind.
    ("invalid-syntax", "actionable"),
    ("io-error", "actionable"),
])
def test_severity_is_derived_from_the_rule_family(code, severity):
    """ruff reports no severity, so this mapping IS the judgment.

    Both directions are covered: pyflakes rules are defects and must be
    actionable, style rules must not be — a linter that marks trailing
    whitespace actionable fails the build on cosmetics and gets switched off.
    """
    (finding,) = _parse([_issue(code=code)])
    assert finding.severity == severity


def test_malformed_json_is_an_ERROR_not_an_empty_result():
    """This test previously asserted the DEFECT, and the reasoning is worth keeping.

    It read: "A crash here takes down the whole analyzer wave. Degrade to
    empty." Half right. Not taking down the wave is correct; degrading to `[]`
    is not, because `[]` already means "the tool looked and found nothing" —
    so a truncated write or a changed output schema reported CLEAN. Measured
    during the US8 sweep: exit 0 + malformed JSON gave
    `skipped=False, findings=0`, indistinguishable from a clean file.

    The new design gets both properties: raise, and let `base.run()` convert it
    to SKIPPED with a reason. The wave survives AND the gap is visible.
    """
    from review_plan_v2.analyzers.base import AnalyzerOutputError

    with pytest.raises(AnalyzerOutputError):
        RuffAnalyzer().parse_output("not json at all", "", [])
    with pytest.raises(AnalyzerOutputError):
        RuffAnalyzer().parse_output('{"not": "a list"}', "", [])


def test_genuinely_empty_output_is_still_a_clean_result():
    """The anti-vacuous half. If EVERY unusual body raised, a clean run would
    report as broken and the gate would be switched off within a week."""
    assert RuffAnalyzer().parse_output("", "", []) == []
    assert RuffAnalyzer().parse_output("[]", "", []) == []


def test_a_junk_row_is_skipped_not_fatal():
    """Asserts WHICH rows survive, not just how many.

    A count plus `any(...)` is satisfied by the valid issue alone, so it held
    whether or not the sparse dict was handled — reported by review.
    """
    findings = _parse(["not a dict", _issue(), {"code": "F401"}])
    assert [f.file for f in findings] == ["scripts/mod.py", ""], (
        "the bare string must be dropped and the sparse dict must survive with "
        "an empty filename, rather than either being silently swallowed"
    )
    assert findings[1].line == 1


def test_a_non_numeric_location_falls_back_to_line_one():
    issue = _issue()
    issue["location"] = {"row": "not-a-number"}
    (finding,) = _parse([issue])
    assert finding.line == 1


def test_only_python_files_are_analyzed():
    """Scope is a constraint like any other. Handing ruff a .ts file wastes a
    subprocess and produces a parse error the operator has to interpret."""
    analyzer = RuffAnalyzer()
    files = [
        FileChange(path="a.py", is_binary=False, is_renamed_from=None,
                   added_lines=(), diff_text="", language="python"),
        FileChange(path="b.ts", is_binary=False, is_renamed_from=None,
                   added_lines=(), diff_text="", language="typescript"),
    ]
    assert [f.path for f in analyzer.applicable_files(files)] == ["a.py"]


def test_the_argv_separates_flags_from_paths():
    """`--` matters: a file named `-x.py` is otherwise read as an option."""
    argv = RuffAnalyzer().build_argv(
        [FileChange(path="-weird.py", is_binary=False, is_renamed_from=None,
                    added_lines=(), diff_text="", language="python")],
        workdir=".",
    )
    assert "--" in argv
    assert argv.index("--") < argv.index("-weird.py")
    assert "--force-exclude" in argv, (
        "without --force-exclude, ruff lints an explicitly-passed path even when "
        "the project excludes it"
    )
    # ORDER, not just presence. A flag after `--` is a FILENAME to ruff, so the
    # exclusion would be silently lost and the run would look normal.
    assert argv.index("--force-exclude") < argv.index("--"), (
        "--force-exclude appears after the -- separator, so ruff reads it as a "
        "path and the project's excludes stop being honoured"
    )


def test_the_ruff_analyzer_runs_in_the_wave():
    """Delivery, not just construction.

    The analyzer being correct is worth nothing if the orchestrator never adds
    it — the same one-line gap that made `needs_manifest=False` a four-times-a-
    session false positive. Asserted from the source of the wave that dispatches
    it, because instantiating the orchestrator here would need a git repo and a
    provider.
    """
    import inspect

    from review_plan_v2 import orchestrator

    source = inspect.getsource(orchestrator.run)
    assert "RuffAnalyzer()" in source, "ruff is not dispatched in the analyzer wave"
    # Review flagged this as unreachable on the theory that `getsource` of a
    # function cannot see module-level imports. That is true in general and does
    # not apply here: the analyzer imports are deliberately FUNCTION-LOCAL, so
    # --version/--help do not pay their import cost. Verified rather than
    # assumed — the assertion below fails if they are ever hoisted, which is the
    # moment this check would silently stop meaning anything.
    assert "from .analyzers.ruff import RuffAnalyzer" in source, (
        "the analyzer import moved to module scope; this check can no longer see "
        "it and needs rewriting against the module source instead"
    )


# --- a crashed analyzer must not read as a clean one (base class, all five) ---


class _FakeCompleted:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_with(monkeypatch, completed, files=None):
    import subprocess as _sp

    from review_plan_v2.analyzers import base as base_mod

    monkeypatch.setattr(base_mod.shutil, "which", lambda _: "/usr/bin/ruff")
    monkeypatch.setattr(_sp, "run", lambda *a, **k: completed)
    monkeypatch.setattr(base_mod.subprocess, "run", lambda *a, **k: completed)
    changed = files if files is not None else [
        FileChange(path="a.py", is_binary=False, is_renamed_from=None,
                   added_lines=(), diff_text="", language="python")
    ]
    return RuffAnalyzer().run(changed, workdir=".")


def test_a_crashed_analyzer_is_reported_skipped_not_clean(monkeypatch):
    """The defect this whole spec exists to close, found in its own base class.

    `run()` used `check=False` — correct, since these tools exit non-zero when
    they FIND something — and then never looked at the code again. A ruff that
    died on a config error returned zero findings, which is byte-identical to a
    clean result at every call site. Reported by review of T005e.
    """
    result = _run_with(monkeypatch, _FakeCompleted(2, "", "ruff failed: invalid rule selector"))
    assert result.skipped is True
    assert "exited 2" in result.skip_reason
    assert "invalid rule selector" in result.skip_reason


def test_a_nonzero_exit_WITH_findings_is_a_normal_result(monkeypatch):
    """The anti-vacuous half, and the reason the rule is not "non-zero = broken".

    Every analyzer here exits non-zero precisely when it has something to say.
    Treating that as failure would skip the gate exactly when it works.
    """
    payload = json.dumps([_issue()])
    result = _run_with(monkeypatch, _FakeCompleted(1, payload, ""))
    assert result.skipped is False
    assert len(result.findings) == 1


def test_a_clean_run_is_a_clean_result(monkeypatch):
    result = _run_with(monkeypatch, _FakeCompleted(0, "[]", ""))
    assert result.skipped is False
    assert result.findings == []



def test_a_parse_error_becomes_a_SKIP_not_a_crash(monkeypatch):
    """Raising is only half the fix; the wave must still survive.

    The original test asserted "degrade to empty" precisely because a crash
    here takes down every other analyzer. That concern was right — so the error
    is converted by `base.run()` into a SKIPPED result carrying the reason,
    which keeps the wave alive AND keeps the gap visible. Both properties, not
    a trade between them.
    """
    result = _run_with(monkeypatch, _FakeCompleted(0, "truncated{[not json", ""))
    assert result.skipped is True
    assert result.findings == []
    assert "could not be parsed" in result.skip_reason
