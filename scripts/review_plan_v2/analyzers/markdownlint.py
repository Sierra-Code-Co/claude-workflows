"""markdownlint-cli analyzer."""
from __future__ import annotations

import json

from ..types import FileChange, Finding
from .base import AnalyzerOutputError, StaticAnalyzer


class MarkdownlintAnalyzer(StaticAnalyzer):
    name = "markdownlint"
    binary = "markdownlint"
    applicable_globs = ("*.md", "*.markdown")

    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        # `--` separator prevents filenames starting with `-` from being interpreted as flags.
        return ["markdownlint", "--json", "--"] + [f.path for f in files]

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        # markdownlint --json emits to stderr
        text = (stderr or stdout).strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # NOT `return []` — that is "looked and found nothing", and this is
            # "said something we cannot read". US8/F1.
            raise AnalyzerOutputError(f"invalid JSON from 'markdownlint': {exc}") from exc
        findings: list[Finding] = []
        # data is dict[file -> list[issue]] or list[issue]
        if isinstance(data, dict):
            for file_path, issues in data.items():
                for issue in issues or []:
                    findings.append(self._make_finding(file_path, issue))
        elif isinstance(data, list):
            for issue in data:
                findings.append(self._make_finding(str(issue.get("fileName", "")), issue))
        return findings

    def _make_finding(self, file_path: str, issue: dict) -> Finding:
        try:
            line = int(issue.get("lineNumber", 1))
        except (TypeError, ValueError):
            line = 1
        return Finding(
            file=file_path,
            line=line,
            line_end=None,
            severity="nit",
            category="docs",
            message=f"{(issue.get('ruleNames') or ['?'])[0]}: {issue.get('ruleDescription', '')}",
            sources=["markdownlint"],
        )
