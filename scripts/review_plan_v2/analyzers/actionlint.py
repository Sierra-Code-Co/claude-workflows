"""actionlint analyzer for GitHub workflow YAML."""
from __future__ import annotations

import json

from ..types import FileChange, Finding
from .base import StaticAnalyzer


class ActionlintAnalyzer(StaticAnalyzer):
    name = "actionlint"
    binary = "actionlint"
    applicable_globs = (".github/workflows/*.yml", ".github/workflows/*.yaml")

    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        # actionlint -format expects a Go text/template; wrap each issue per-line as JSON
        # then we parse line-by-line. `-` separator before the file list prevents
        # filenames starting with `-` from being interpreted as flags.
        return ["actionlint", "-format", "{{json .}}", "--"] + [f.path for f in files]

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        text = stdout.strip()
        if not text:
            return []
        # actionlint with `{{json .}}` emits one JSON object per issue on its own line,
        # OR a JSON array depending on version. Try array first, fall back to NDJSON.
        items: list[dict] = []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                items = [d for d in data if isinstance(d, dict)]
            elif isinstance(data, dict):
                items = [data]
        except json.JSONDecodeError:
            for raw_line in text.splitlines():
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                    if isinstance(obj, dict):
                        items.append(obj)
                except json.JSONDecodeError:
                    continue
        findings: list[Finding] = []
        for issue in items:
            filepath = str(issue.get("filepath", "") or "").strip()
            if not filepath:
                # Skip findings without a file — would render as malformed `[ACTIONABLE] :1 ...`
                continue
            try:
                line = int(issue.get("line", 1))
            except (TypeError, ValueError):
                line = 1
            findings.append(Finding(
                file=filepath,
                line=line,
                line_end=None,
                severity="actionable",
                category="bug",
                message=str(issue.get("message", "")),
                sources=["actionlint"],
            ))
        return findings
