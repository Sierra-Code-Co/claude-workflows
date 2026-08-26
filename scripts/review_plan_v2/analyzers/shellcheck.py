"""shellcheck analyzer."""
from __future__ import annotations

import json

from ..types import FileChange, Finding
from .base import AnalyzerOutputError, StaticAnalyzer

_LEVEL_MAP = {
    "error": ("actionable", "bug"),
    "warning": ("nit", "style"),
    "info": ("info", "style"),
    "style": ("info", "style"),
}


class ShellcheckAnalyzer(StaticAnalyzer):
    name = "shellcheck"
    binary = "shellcheck"
    applicable_globs = ("*.sh", "*.bash")

    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        # `--` separator prevents filenames starting with `-` from being interpreted as flags.
        return ["shellcheck", "--format=json", "--"] + [f.path for f in files]

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        text = stdout.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # NOT `return []` — that is "looked and found nothing", and this is
            # "said something we cannot read". US8/F1.
            raise AnalyzerOutputError(f"invalid JSON from 'shellcheck': {exc}") from exc
        if not isinstance(data, list):
            # Valid JSON of the WRONG SHAPE is the same defect through a
            # different door: it parsed, so the decoder never objected, and
            # `[]` says "looked and found nothing". A schema change upstream
            # lands exactly here.
            raise AnalyzerOutputError(
                f"shellcheck returned {type(data).__name__}, expected a list of findings")
        findings: list[Finding] = []
        for issue in data:
            if not isinstance(issue, dict):
                continue
            sev, cat = _LEVEL_MAP.get(str(issue.get("level", "info")), ("info", "style"))
            try:
                line = int(issue.get("line", 1))
            except (TypeError, ValueError):
                line = 1
            findings.append(Finding(
                file=str(issue.get("file", "")),
                line=line,
                line_end=None,
                severity=sev,
                category=cat,
                message=f"SC{issue.get('code', '')}: {issue.get('message', '')}",
                sources=["shellcheck"],
            ))
        return findings
