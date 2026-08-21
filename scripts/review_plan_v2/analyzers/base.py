"""StaticAnalyzer ABC. Subprocess invocation with shell=False; explicit changed-file lists."""
from __future__ import annotations

import fnmatch
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable

from ..types import FileChange, Finding


class AnalyzerOutputError(Exception):
    """The analyzer ran but its output could not be understood (US8/F1).

    Raised by `parse_output` instead of returning `[]`. The distinction is the
    whole point: `[]` means "the tool looked and found nothing", and an
    unparseable body means "the tool told us something we cannot read". Both
    used to produce zero findings, so a truncated write or a changed output
    schema reported CLEAN.

    T005e/#38 closed the neighbouring case — non-zero exit AND empty. This is
    the half that fix does not cover: **exit 0 with garbage on stdout**, which
    `base.run()` had no way to tell from success.
    """


@dataclass
class AnalyzerResult:
    name: str
    findings: list[Finding] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


class StaticAnalyzer(ABC):
    name: str = ""
    binary: str = ""
    applicable_globs: tuple[str, ...] = ()

    def is_installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def applicable_files(self, files: Iterable[FileChange]) -> list[FileChange]:
        out: list[FileChange] = []
        for f in files:
            if f.is_binary:
                continue
            for g in self.applicable_globs:
                if fnmatch.fnmatch(f.path, g):
                    out.append(f)
                    break
        return out

    @abstractmethod
    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        """Parse analyzer subprocess output → Finding[]. Required for default run()."""
        ...

    @abstractmethod
    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        """Construct subprocess argv. Required for default run()."""
        ...

    def run(self, all_files: Iterable[FileChange], workdir: str = ".") -> AnalyzerResult:
        if not self.is_installed():
            msg = f"{self.binary} not installed; skipped {self.name}. Install: brew install {self.binary}"
            print(f"WARNING: {msg}", file=sys.stderr)
            return AnalyzerResult(name=self.name, skipped=True, skip_reason=msg)
        files = self.applicable_files(all_files)
        if not files:
            return AnalyzerResult(name=self.name, findings=[])
        argv = self.build_argv(files, workdir)
        try:
            # check=False — analyzers exit non-zero when they find issues; that's expected.
            out = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=workdir, shell=False, check=False)
        except subprocess.TimeoutExpired:
            return AnalyzerResult(name=self.name, skipped=True, skip_reason=f"{self.name} timed out after 60s")
        try:
            findings = self.parse_output(out.stdout, out.stderr, files)
        except AnalyzerOutputError as exc:
            # Unreadable output is ABSENT COVERAGE, never a clean file.
            return AnalyzerResult(
                name=self.name, skipped=True,
                skip_reason=(
                    f"produced output that could not be parsed, so nothing it "
                    f"looked at was actually checked: {exc}"
                ),
            )
        # A NON-ZERO EXIT WITH NOTHING TO REPORT MEANS THE TOOL COULD NOT DO ITS
        # JOB — a config error, an unreadable file, an output-schema change,
        # a missing rule set. Every analyzer here exits non-zero when it FINDS
        # something, which is why the call above uses check=False; but in that
        # case it also returns findings. Non-zero AND empty is the signature of
        # failure, and it was previously indistinguishable from a clean result
        # at every call site — the exact defect this portfolio exists to close,
        # sitting in the base class shared by all five analyzers.
        #
        # Reported as SKIPPED rather than raised: one broken analyzer must not
        # abort the wave, and `analyzers_skipped` already surfaces in the run
        # summary, so the operator sees "ruff (exited 2 …)" instead of silence.
        if out.returncode != 0 and not findings:
            detail = (out.stderr or out.stdout or "").strip().splitlines()
            first = detail[0][:200] if detail else "no output"
            return AnalyzerResult(
                name=self.name, skipped=True,
                skip_reason=(f"exited {out.returncode} and reported nothing, so it "
                             f"did not run as expected: {first}"),
            )
        return AnalyzerResult(name=self.name, findings=findings)
