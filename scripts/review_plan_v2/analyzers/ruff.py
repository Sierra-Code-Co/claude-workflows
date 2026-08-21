"""ruff analyzer — the Python linter this Python project did not have (T005e).

Discovered while doing T005b: the gate portfolio covered shell, YAML/Actions,
markdown and secrets, and had nothing at all for the language the tool is
written in. `ruff` found 20 real issues in the repo on its first run, three of
them unused imports in `scripts/` that nothing here would ever have reported.

One of the twenty is worth naming, because it is why this gate is not merely
tidiness. `F841` (unused local) fired on a security test whose only assertion
was that a marker file did NOT appear — so it passed just as well when the
parser under test never ran, since a crashed entrypoint also creates no marker.
The unused variable was the tell. A linter found a vacuous test that five
rounds of human and LLM review had not.

**Blocking from the first commit, not advisory.** FR-014 asks a new gate to
enter at advisory tier and earn promotion with measured acceptance, and the
reason is noise: markdownlint's 2541-finding baseline is the cautionary case in
this repo's own history. That reasoning does not apply at a baseline of ZERO.
All twenty findings were fixed in the same change, so there is no backlog to
grant amnesty to, and a report-only check over a clean baseline is where
checkers go to die — the same argument `.github/workflows/tests.yml` already
makes for itself in its header.
"""
from __future__ import annotations

import json

from ..types import FileChange, Finding
from .base import AnalyzerOutputError, StaticAnalyzer


#: Codes ruff emits that are NOT rule ids. A file that does not parse is
#: reported as `invalid-syntax`, with no numeric code at all — so the
#: prefix-matching below saw a string starting with "i", fell through every
#: branch, and classified THE MOST SEVERE THING RUFF CAN REPORT as a style nit.
#:
#: Shipped in T005e and found on 2026-08-16 while trying to use ruff as the
#: trigger for FR-012's short-circuit: the deliberately broken file produced a
#: `nit`, so nothing short-circuited and the probe ran the full review. The
#: classifier was wrong, not the ordering. Derived from ruff's actual JSON
#: output rather than from the rule-code scheme I had in mind — the same
#: recall-vs-derive failure this repo keeps recording.
_NON_RULE_CODES = {
    "invalid-syntax",   # the file does not parse
    "io-error",         # the file could not be read
}


#: ruff reports no severity, so it is derived from the rule family. `F` is
#: pyflakes — real defects (undefined names, unused imports, f-strings missing
#: placeholders). `E9` is syntax/IO errors. Everything else is style.
def _classify(code: str) -> tuple[str, str]:
    if code in _NON_RULE_CODES:
        return "actionable", "bug"
    if code.startswith("E9") or code.startswith("F82"):
        return "actionable", "bug"
    if code.startswith("F"):
        return "actionable", "correctness"
    return "nit", "style"


class RuffAnalyzer(StaticAnalyzer):
    name = "ruff"
    binary = "ruff"
    applicable_globs = ("*.py",)

    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        # `--force-exclude` makes ruff honour the project's exclude settings even
        # for paths passed explicitly, so a file the repo has deliberately
        # excluded is not linted just because it appears in a diff.
        # `--` separates flags from paths, so a filename starting with `-` is
        # never read as an option.
        return [
            "ruff", "check", "--output-format=json", "--no-cache",
            "--force-exclude", "--",
        ] + [f.path for f in files]

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        text = stdout.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # NOT `return []` — that is "looked and found nothing", and this is
            # "said something we cannot read". US8/F1.
            raise AnalyzerOutputError(f"invalid JSON from 'ruff': {exc}") from exc
        if not isinstance(data, list):
            # Valid JSON of the WRONG SHAPE is the same defect through a
            # different door: it parsed, so the decoder never objected, and
            # `[]` says "looked and found nothing". A schema change upstream
            # lands exactly here.
            raise AnalyzerOutputError(
                f"ruff returned {type(data).__name__}, expected a list of findings")
        findings: list[Finding] = []
        for issue in data:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "")
            severity, category = _classify(code)
            location = issue.get("location")
            line = 1
            if isinstance(location, dict):
                try:
                    line = int(location.get("row", 1))
                except (TypeError, ValueError):
                    line = 1
            end = issue.get("end_location")
            line_end = None
            if isinstance(end, dict):
                try:
                    row = int(end.get("row", line))
                    line_end = row if row != line else None
                except (TypeError, ValueError):
                    line_end = None
            message = str(issue.get("message", "")).strip()
            findings.append(Finding(
                file=str(issue.get("filename", "")),
                line=line,
                line_end=line_end,
                severity=severity,
                category=category,
                message=f"{code}: {message}" if code else message,
                sources=["ruff"],
            ))
        return findings
