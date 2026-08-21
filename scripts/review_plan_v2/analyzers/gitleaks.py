"""Gitleaks analyzer with line-overlap filter (only reports secrets in diff-added lines)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dataclasses import dataclass, field

from ..paths import contained
from ..types import FileChange, Finding
from .base import AnalyzerResult, StaticAnalyzer


@dataclass
class GitleaksResult(AnalyzerResult):
    """Carries WHICH files were never scanned (T005j).

    `AnalyzerResult` has `skipped`/`skip_reason` for a whole-analyzer skip and
    nothing for partial coverage, so a per-file skip had nowhere to go and went
    nowhere. Modelled on `StructuralResult.refused_paths`, for the same reason:
    zero findings from a file nobody read is not a clean file.
    """

    not_scanned: list[tuple[str, str]] = field(default_factory=list)

    @property
    def coverage_is_complete(self) -> bool:
        return not self.not_scanned

    def coverage_gaps(self) -> list[str]:
        return [
            f"gitleaks did NOT scan {path} ({reason}) — no secret finding for "
            f"this file means nothing was read, not that nothing is there"
            for path, reason in self.not_scanned
        ]


class GitleaksAnalyzer(StaticAnalyzer):
    name = "gitleaks"
    binary = "gitleaks"
    applicable_globs = ("*",)  # all non-binary text files

    def applicable_files(self, files):
        return [f for f in files if not f.is_binary]

    # GitleaksAnalyzer overrides run() entirely — these stubs satisfy the ABC
    # but are never invoked. The real argv + parsing live inside run().
    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        return []

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        return []

    def run(self, all_files, workdir: str = "."):
        if not self.is_installed():
            msg = "gitleaks not installed; skipped (this disables secret detection — install: brew install gitleaks)"
            print(f"WARNING: {msg}", file=sys.stderr)
            return AnalyzerResult(name=self.name, skipped=True, skip_reason=msg)
        files = self.applicable_files(all_files)
        if not files:
            return AnalyzerResult(name=self.name, findings=[])

        # T005j. Three `continue`s in the staging loop below each meant a file
        # was NEVER SCANNED FOR SECRETS, and each produced zero findings —
        # byte-identical to clean, at every call site. FR-004's rule ("absent
        # coverage is reported as absent") applied where it matters most: this
        # is the gate whose silence is most expensive.
        not_scanned: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory(prefix="rpv2-gitleaks-") as tmp:
            tmp_path = Path(tmp).resolve()
            for f in files:
                # Reconstruct file content from working tree, not from diff
                src = Path(workdir) / f.path
                if not src.exists():
                    # A file in the diff with NO added lines is a deletion (or
                    # a pure-removal hunk). gitleaks only reports secrets on
                    # ADDED lines, so there was nothing here to find and the
                    # skip is correct — reporting it would fire on most diffs,
                    # and a banner that fires every run is one nobody reads.
                    #
                    # A file with added lines that is NOT on disk is the
                    # opposite: new content exists and nothing scanned it.
                    if f.added_lines:
                        not_scanned.append((f.path, "not present in the working tree"))
                    continue
                dest = (tmp_path / f.path).resolve()
                # Path traversal guard: dest must stay inside tmp_path. This is
                # a WRITE target, so an escape here would not merely stage the
                # wrong file — `shutil.copyfile` below would clobber it.
                if not contained(dest, tmp_path):
                    not_scanned.append((f.path, "resolved outside the staging directory"))
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(src, dest)
                except (OSError, shutil.SameFileError) as exc:
                    not_scanned.append((f.path, f"could not be staged: {exc}"))
                    continue
            # Copy .gitleaks.toml if present (allowlist + custom rules)
            gl_toml = Path(workdir) / ".gitleaks.toml"
            if gl_toml.exists():
                shutil.copyfile(gl_toml, tmp_path / ".gitleaks.toml")

            report_path = tmp_path / "_report.json"
            argv = [
                "gitleaks", "detect",
                "--source", str(tmp_path),
                "--no-git", "--redact",
                "--report-format", "json",
                "--report-path", str(report_path),
                "--exit-code", "0",  # always exit 0; we read the report
            ]
            try:
                # check=False — we passed --exit-code 0 + always read the JSON report; non-zero exit is fine.
                subprocess.run(argv, capture_output=True, text=True, timeout=60, shell=False, check=False)
            except subprocess.TimeoutExpired:
                return GitleaksResult(name=self.name, skipped=True, not_scanned=not_scanned,
                                      skip_reason="gitleaks timed out after 60s")

            findings: list[Finding] = []
            if report_path.exists():
                try:
                    raw = json.loads(report_path.read_text(encoding="utf-8") or "[]")
                except json.JSONDecodeError:
                    raw = []
                tmp_prefix = str(tmp_path).rstrip(os.sep) + os.sep
                if isinstance(raw, list):
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        gl_file = str(item.get("File", ""))
                        # Gitleaks reports absolute paths inside the temp dir; strip to repo-relative.
                        rel_file = gl_file[len(tmp_prefix):] if gl_file.startswith(tmp_prefix) else gl_file
                        # Defensive: StartLine/Line may exist but be None — int(None) raises TypeError.
                        line_raw = item.get("StartLine")
                        if line_raw is None:
                            line_raw = item.get("Line")
                        try:
                            line_no = int(line_raw) if line_raw is not None else 1
                        except (TypeError, ValueError):
                            line_no = 1
                        msg = str(item.get("Description", "secret detected"))
                        findings.append(Finding(
                            file=rel_file, line=line_no, line_end=None,
                            severity="actionable", category="secrets",
                            message=msg, sources=["gitleaks"],
                        ))

            findings = filter_to_diff_lines(findings, files)
            return GitleaksResult(name=self.name, findings=findings,
                                  not_scanned=not_scanned)


def filter_to_diff_lines(findings: list[Finding], files: list[FileChange]) -> list[Finding]:
    """Drop findings whose line is outside the diff's added/modified ranges."""
    by_path = {f.path: f.added_lines for f in files}
    kept: list[Finding] = []
    for fnd in findings:
        ranges = by_path.get(fnd.file)
        if ranges is None:
            # Not in our changed-file set; skip
            continue
        if any(start <= fnd.line <= end for (start, end) in ranges):
            kept.append(fnd)
    return kept
