"""Structural completeness gate — ast-grep as an enumerator (US3, T017/T018).

The question this answers is "did I get all the sites?", and it is a DETERMINISTIC
question, so constitution Principle III forbids routing it to a reviewer. A
reviewer reads a diff; the sites it is being asked about are by definition the
ones not in the diff. On mtg-cube-ai #2071 that question was put to a reviewer
five times and answered wrong four of them.

THE ONE RULE THIS MODULE MUST NEVER BREAK: absent coverage is reported as absent,
never as clean. There are four ways coverage can be absent here —

  1. ast-grep is not installed
  2. no rules are configured
  3. a rule file fails to parse
  4. an ast-grep invocation errors

— and every one of them produces an empty findings list. An empty findings list
rendered without its provenance is the exact output a clean repo produces, which
is how three separate checks in this fleet read as passing for months. So the
result carries `rules: list[RuleOutcome]`, and `coverage_is_complete` is false
unless every configured rule actually ran.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..analyzers.base import AnalyzerResult, StaticAnalyzer
from ..paths import safe_join
from ..types import FileChange, Finding

# ast-grep's `language:` key → the file globs whose changes can possibly match.
# Deliberately not open-ended: an unknown language is an explicit error below
# rather than a rule that quietly applies to nothing.
_LANGUAGE_GLOBS: dict[str, tuple[str, ...]] = {
    "typescript": ("*.ts", "*.mts", "*.cts"),
    "tsx": ("*.tsx",),
    "javascript": ("*.js", "*.mjs", "*.cjs"),
    "jsx": ("*.jsx",),
    "python": ("*.py",),
    "go": ("*.go",),
    "rust": ("*.rs",),
    "bash": ("*.sh", "*.bash"),
    "yaml": ("*.yml", "*.yaml"),
}

_SEVERITY_MAP = {
    "error": ("actionable", "correctness"),
    "warning": ("nit", "consistency"),
    "info": ("info", "style"),
    "hint": ("info", "style"),
}


@dataclass
class RuleOutcome:
    """Per-rule provenance. `ran=False` is why this type exists."""

    rule_id: str
    path: str
    ran: bool
    match_count: int = 0
    error: str | None = None


@dataclass
class StructuralResult(AnalyzerResult):
    rules: list[RuleOutcome] = field(default_factory=list)
    # How many changed files ANY structural rule could conceivably have
    # covered. `None` means "not determined", which is treated as a gap: an
    # unknown must never resolve in favour of "covered".
    coverable_file_count: int | None = None
    # Changed files refused for lying outside `workdir` (T005h). Named, never
    # merely counted, and surfaced through coverage_gaps() — a refused target is
    # a file NOBODY checked, which is the exact state this module exists to stop
    # rendering as clean.
    refused_paths: list[str] = field(default_factory=list)

    @property
    def had_nothing_to_cover(self) -> bool:
        """No code changed that any rule language could apply to.

        This exists so the absent-coverage banner does not fire on every
        markdown-only PR in every repo that has not adopted rules yet. FR-004
        requires reporting absent coverage; it does not require reporting it
        where no completeness question was ever posed, and a banner that fires
        on every run is one nobody reads by the third week — which would cost
        exactly the signal FR-004 is buying.

        A refused file makes this FALSE, and getting that wrong is subtle:
        refused paths are removed from `files` before `coverable_file_count` is
        computed, so a run whose only coverable file was refused counts zero and
        looked exactly like a markdown-only PR. There WAS a completeness
        question — the gate declined to answer it. Fixing it here rather than in
        each consumer is what makes the distinction hold everywhere; the first
        version patched `coverage_is_complete` alone and `coverage_gaps()` went
        on silently swallowing the skip reason, which a test caught.
        """
        if self.refused_paths:
            return False
        return self.coverable_file_count == 0

    @property
    def coverage_is_complete(self) -> bool:
        """True only if every configured rule ran — or there was nothing to run on.

        The `bool(self.rules)` half is load-bearing: `all([])` is True, so an
        empty rule set would otherwise report complete coverage of nothing.
        """
        # Checked FIRST, and before had_nothing_to_cover. A run whose only
        # coverable files were all refused has coverable_file_count == 0, so
        # without this the escape hatch would report complete coverage of a set
        # it declined to look at — "clean because we skipped it".
        if self.refused_paths:
            return False
        if self.had_nothing_to_cover:
            return True
        return bool(self.rules) and all(r.ran for r in self.rules)

    def coverage_gaps(self) -> list[str]:
        # Refused paths are reported on EVERY exit path, including the two early
        # returns and the nothing-to-cover case. A file dropped for escaping the
        # workdir is uncovered no matter why the rest of the run ended, and the
        # early returns are precisely where a gap is easiest to lose.
        refused = [
            f"refused to analyze (outside the working directory): {p}"
            for p in self.refused_paths
        ]
        if self.had_nothing_to_cover:
            return refused
        if self.skipped:
            return refused + [self.skip_reason]
        return refused + [f"{r.rule_id}: {r.error}" for r in self.rules if not r.ran]


class StructuralAnalyzer(StaticAnalyzer):
    name = "structural"
    binary = "ast-grep"
    # Superset placeholder; the real set is computed per-instance from the
    # loaded rules' `language:` keys, since a repo with only Python rules
    # should not be handed .ts files.
    applicable_globs = tuple(g for gs in _LANGUAGE_GLOBS.values() for g in gs)

    def __init__(self, rules_dir: str | Path | None = None) -> None:
        self.rules_dir = Path(rules_dir) if rules_dir else Path.cwd() / "rules"

    # --- rule loading --------------------------------------------------------

    def rule_files(self) -> list[Path]:
        if not self.rules_dir.is_dir():
            return []
        return sorted(p for p in self.rules_dir.glob("*.yml"))

    def _load_rule(self, path: Path) -> tuple[str, tuple[str, ...], str | None]:
        """→ (rule_id, globs, error). A parse failure is an error, not a skip."""
        try:
            doc = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            return (path.stem, (), f"could not parse rule file: {exc}")
        if not isinstance(doc, dict):
            return (path.stem, (), "rule file is not a mapping")
        rule_id = str(doc.get("id") or path.stem)
        lang = str(doc.get("language", "")).lower()
        globs = _LANGUAGE_GLOBS.get(lang)
        if not globs:
            return (rule_id, (), f"unsupported or missing `language:` ({lang!r})")
        return (rule_id, globs, None)

    # --- required by the ABC -------------------------------------------------

    def build_argv(self, files: list[FileChange], workdir: str) -> list[str]:
        # Unused: run() invokes once per rule, since `ast-grep scan --rule`
        # accepts exactly one rule file and per-rule invocation is what gives
        # each gate its own health. Implemented because the ABC requires it.
        raise NotImplementedError("StructuralAnalyzer runs one invocation per rule")

    def parse_output(self, stdout: str, stderr: str, files: list[FileChange]) -> list[Finding]:
        text = stdout.strip()
        if not text:
            return []
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        findings: list[Finding] = []
        for m in data:
            if not isinstance(m, dict):
                continue
            sev, cat = _SEVERITY_MAP.get(str(m.get("severity", "error")), ("actionable", "correctness"))
            start = (m.get("range") or {}).get("start") or {}
            findings.append(Finding(
                file=str(m.get("file", "")),
                # ast-grep reports 0-indexed lines; every other analyzer here
                # is 1-indexed, and the renderer does not normalise.
                line=int(start.get("line", 0)) + 1,
                line_end=None,
                severity=sev,
                category=cat,
                message=f"[{m.get('ruleId', '?')}] {m.get('message', '')}",
                sources=["ast-grep"],
            ))
        return findings

    # --- the run -------------------------------------------------------------

    def run(self, all_files: Iterable[FileChange], workdir: str = ".") -> StructuralResult:
        # T005h. Target paths come from the diff, so they are repo-relative in
        # practice — but nothing in this code enforced it, and `_files_for_globs`
        # uses fnmatch, where `*` matches `/`, so a glob is no barrier either.
        # Partitioned before anything else runs, so no later branch can hand an
        # escaping path to the subprocess.
        files, refused = self._partition_contained(all_files, workdir)
        # Computed BEFORE any early return, so every exit path can distinguish
        # "no coverage" from "nothing needed covering".
        coverable = len(self._files_for_globs(files, self.applicable_globs))

        if shutil.which(self.binary) is None:
            # NOT a pass. The enumerator is the entire gate.
            return StructuralResult(
                name=self.name,
                skipped=True,
                coverable_file_count=coverable,
                refused_paths=refused,
                skip_reason=(
                    "ast-grep is not installed, so NO deterministic completeness "
                    "checking ran. This is absent coverage, not a clean result. "
                    "Install: brew install ast-grep"
                ),
            )

        rule_paths = self.rule_files()
        if not rule_paths:
            # FR-004 acceptance 4. Silence here is the whole defect class.
            return StructuralResult(
                name=self.name,
                skipped=True,
                coverable_file_count=coverable,
                refused_paths=refused,
                skip_reason=(
                    f"no structural rules configured in {self.rules_dir}, so "
                    f"completeness questions have NO deterministic coverage in "
                    f"this repo. Reviewers cannot answer them (Principle III); "
                    f"they are simply unanswered."
                ),
            )

        outcomes: list[RuleOutcome] = []
        findings: list[Finding] = []

        for path in rule_paths:
            rule_id, globs, err = self._load_rule(path)
            if err:
                outcomes.append(RuleOutcome(rule_id, str(path), ran=False, error=err))
                continue

            targets = [f.path for f in self._files_for_globs(files, globs)]
            if not targets:
                # Nothing this rule could apply to changed. Genuinely ran to
                # completion over an empty target set — distinct from failing.
                outcomes.append(RuleOutcome(rule_id, str(path), ran=True, match_count=0))
                continue

            argv = ["ast-grep", "scan", "--rule", str(path), "--json", "--"] + targets
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, timeout=60,
                    cwd=workdir, shell=False, check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                outcomes.append(RuleOutcome(rule_id, str(path), ran=False, error=str(exc)))
                continue

            # 0 = no matches, 1 = matches found. Anything else is a real error
            # and must not be read as "no matches".
            if proc.returncode not in (0, 1):
                outcomes.append(RuleOutcome(
                    rule_id, str(path), ran=False,
                    error=f"ast-grep exited {proc.returncode}: {proc.stderr.strip()[:200]}",
                ))
                continue

            try:
                rule_findings = self.parse_output(proc.stdout, proc.stderr, files)
            except json.JSONDecodeError as exc:
                outcomes.append(RuleOutcome(rule_id, str(path), ran=False, error=f"bad JSON: {exc}"))
                continue

            findings.extend(rule_findings)
            outcomes.append(RuleOutcome(rule_id, str(path), ran=True, match_count=len(rule_findings)))

        return StructuralResult(
            name=self.name, findings=findings, rules=outcomes,
            coverable_file_count=coverable, refused_paths=refused,
        )

    @staticmethod
    def _partition_contained(
        files: Iterable[FileChange], workdir: str,
    ) -> tuple[list[FileChange], list[str]]:
        """→ (analyzable, refused). Refused paths are NAMED, never dropped quietly.

        `safe_join` refuses absolute paths, `..` segments, and — the case no
        textual check can reach — a path that resolves outside `workdir` through
        a symlink. A dropped target is a file nobody examined, so it travels
        back to the caller and lands in `coverage_gaps()`.
        """
        safe: list[FileChange] = []
        refused: list[str] = []
        for f in files:
            if safe_join(workdir, f.path) is None:
                refused.append(f.path)
            else:
                safe.append(f)
        return safe, refused

    @staticmethod
    def _files_for_globs(files: Iterable[FileChange], globs: tuple[str, ...]) -> list[FileChange]:
        import fnmatch

        out = []
        for f in files:
            if f.is_binary:
                continue
            if any(fnmatch.fnmatch(f.path, g) for g in globs):
                out.append(f)
        return out
