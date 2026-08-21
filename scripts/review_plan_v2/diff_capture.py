"""Capture git diff vs base ref. Produces Diff structures with per-file FileChanges.

Base-ref detection chain (R-9): explicit --base → origin/HEAD → main → master → develop → staging → error.
"""
from __future__ import annotations

import re
import subprocess
from typing import Iterable

from .types import Diff, FileChange


CHUNK_LINE_THRESHOLD = 1500
LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".sh": "shell", ".bash": "shell", ".md": "markdown",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".java": "java", ".kt": "kotlin", ".swift": "swift",
    ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
}


class DiffCaptureError(Exception):
    """Raised when diff capture fails (no base ref, detached HEAD, etc.)."""


def _git(*args: str, cwd: str | None = None) -> str:
    """Run a git command, return stdout. Raises CalledProcessError on failure."""
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=cwd
    )
    return out.stdout


def head_sha(cwd: str | None = None) -> str | None:
    """Public helper: return the SHA of HEAD, or None on failure."""
    try:
        return _git("rev-parse", "HEAD", cwd=cwd).strip()
    except subprocess.CalledProcessError:
        return None


def detect_base_ref(explicit: str | None = None, cwd: str | None = None) -> str:
    """Find a usable base ref. Explicit wins; otherwise try the standard chain."""
    if explicit:
        try:
            _git("rev-parse", "--verify", explicit, cwd=cwd)
            return explicit
        except subprocess.CalledProcessError as e:
            raise DiffCaptureError(f"--base {explicit!r} does not resolve to a ref") from e

    try:
        out = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd).strip()
        if out:
            return out
    except subprocess.CalledProcessError:
        pass

    for candidate in ("main", "master", "develop", "staging"):
        try:
            _git("rev-parse", "--verify", candidate, cwd=cwd)
            return candidate
        except subprocess.CalledProcessError:
            continue

    raise DiffCaptureError(
        "no base ref found (tried origin/HEAD, main, master, develop, staging). "
        "Pass --base <branch> explicitly."
    )


def detect_head(cwd: str | None = None) -> str:
    try:
        ref = _git("symbolic-ref", "--short", "HEAD", cwd=cwd).strip()
        return ref or "HEAD"
    except subprocess.CalledProcessError as e:
        # Detached HEAD — return the SHA but flag for orchestrator
        sha = _git("rev-parse", "HEAD", cwd=cwd).strip()
        raise DiffCaptureError(
            f"detached HEAD at {sha}; pass --base explicitly and check out a branch"
        ) from e


def _language_for(path: str) -> str | None:
    for ext, lang in LANG_BY_EXT.items():
        if path.endswith(ext):
            return lang
    return None


def _is_binary_diff(diff_text: str) -> bool:
    return "Binary files" in diff_text and "differ" in diff_text


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _added_line_ranges(diff_text: str) -> tuple[tuple[int, int], ...]:
    """Parse `@@ -a,b +c,d @@` hunk headers + per-line `+` markers to extract added line ranges."""
    ranges: list[tuple[int, int]] = []
    cur_line = 0
    in_added = False
    added_start = 0
    for raw in diff_text.splitlines():
        m = _HUNK_HEADER.match(raw)
        if m:
            if in_added:
                ranges.append((added_start, cur_line - 1))
                in_added = False
            cur_line = int(m.group(1))
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            if not in_added:
                added_start = cur_line
                in_added = True
            cur_line += 1
        elif raw.startswith("-"):
            # deletion — does not advance new-file line counter
            continue
        else:
            if in_added:
                ranges.append((added_start, cur_line - 1))
                in_added = False
            if not raw.startswith("\\"):  # skip "\ No newline at end of file"
                cur_line += 1
    if in_added:
        ranges.append((added_start, cur_line - 1))
    return tuple(ranges)


def capture_diff(base: str | None, scope: str = "all", cwd: str | None = None) -> Diff:
    """Capture the diff vs base. Returns Diff with per-file FileChanges including added-line ranges."""
    base_ref = detect_base_ref(base, cwd=cwd)
    head_ref = detect_head(cwd=cwd)

    # Resolve base..HEAD spec; respect scope
    if scope == "uncommitted":
        diff_args = ["diff", "--no-ext-diff", "-M"]
    elif scope == "committed":
        diff_args = ["diff", "--no-ext-diff", "-M", f"{base_ref}...HEAD"]
    else:  # all
        diff_args = ["diff", "--no-ext-diff", "-M", f"{base_ref}...HEAD"]

    # First pass: name-status for added/removed/renamed signals
    name_status_raw = _git(*diff_args, "--name-status", cwd=cwd)
    name_status: dict[str, tuple[str, str | None]] = {}
    for line in name_status_raw.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        code = parts[0][0]
        if code == "R" and len(parts) >= 3:
            name_status[parts[2]] = ("R", parts[1])
        elif len(parts) >= 2:
            name_status[parts[-1]] = (code, None)

    # Per-file diffs
    files: list[FileChange] = []
    for path, (code, renamed_from) in name_status.items():
        if code == "D":
            # Deletion: record but no added lines
            file_diff_text = _git(*diff_args, "--", path, cwd=cwd)
            files.append(FileChange(
                path=path, is_binary=False, is_renamed_from=None,
                added_lines=(), diff_text=file_diff_text, language=_language_for(path),
            ))
            continue

        file_diff_text = _git(*diff_args, "--", path, cwd=cwd)
        is_bin = _is_binary_diff(file_diff_text)
        added = () if is_bin else _added_line_ranges(file_diff_text)
        files.append(FileChange(
            path=path,
            is_binary=is_bin,
            is_renamed_from=renamed_from,
            added_lines=added,
            diff_text=file_diff_text,
            language=_language_for(path),
        ))

    return Diff(base_ref=base_ref, head_ref=head_ref, files=tuple(files))


def chunk_file(file: FileChange, threshold: int = CHUNK_LINE_THRESHOLD) -> list[FileChange]:
    """Split a large file's diff into multiple FileChanges by hunk boundary."""
    line_count = file.diff_text.count("\n")
    if line_count <= threshold or file.is_binary:
        return [file]

    chunks: list[str] = []
    current: list[str] = []
    current_lines = 0
    header_lines: list[str] = []
    seen_first_hunk = False

    for raw in file.diff_text.splitlines(keepends=True):
        if not seen_first_hunk and not raw.startswith("@@"):
            header_lines.append(raw)
            continue
        if raw.startswith("@@") and current_lines >= threshold:
            chunks.append("".join(header_lines + current))
            current = [raw]
            current_lines = 1
            seen_first_hunk = True
            continue
        current.append(raw)
        current_lines += 1
        if raw.startswith("@@"):
            seen_first_hunk = True

    if current:
        chunks.append("".join(header_lines + current))

    if not chunks:
        # Defensive: no hunk headers found (malformed/empty diff). Return original.
        return [file]

    return [
        FileChange(
            path=file.path,
            is_binary=file.is_binary,
            is_renamed_from=file.is_renamed_from,
            added_lines=_added_line_ranges(c),
            diff_text=c,
            language=file.language,
        )
        for c in chunks
    ]


def chunked_files(diff: Diff, threshold: int = CHUNK_LINE_THRESHOLD) -> Iterable[FileChange]:
    """Yield diff.files with large files split into multiple chunks."""
    for f in diff.files:
        for c in chunk_file(f, threshold=threshold):
            yield c
