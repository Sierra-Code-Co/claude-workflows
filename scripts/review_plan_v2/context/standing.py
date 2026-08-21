"""Operator-declared context attached to every reviewer call (T045, #18).

`always_include_files` in `.review-plan-v2.yaml` names files the reviewers should
always see: a conventions doc, a schema, the one interface every finding gets
wrong. Filed 2026-04-30 and unbuilt until now.

The load-bearing detail is the empty-glob report. A glob that matches no file
produces no context, and no context is byte-identical to "there was nothing to
attach" — so a typo'd path silently disables the feature while the operator
believes it is on. This repo has hit that exact class four times in scoped lint
and scan configs (`scope-config-test`), which is why the miss is reported rather
than inferred.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..paths import contained
from ._types import ContextBlock

if TYPE_CHECKING:  # import at type-check time only; the runtime import inside
    from .related import ContextReport  # gather() avoids a circular import

#: Per-file ceiling. A standing file is operator-declared, but declaring one by
#: mistake (a lockfile, a build artefact) must not be able to consume the whole
#: budget before derived context is even considered.
MAX_STANDING_FILE_CHARS = 20_000


def gather(repo_root: Path | str, globs: list[str]) -> tuple[list[ContextBlock], "ContextReport"]:
    from .related import ContextReport  # local import avoids a cycle

    repo_root = Path(repo_root)
    report = ContextReport()
    blocks: list[ContextBlock] = []
    root = repo_root.resolve()

    for pattern in globs or []:
        matched = 0
        # `Path.glob` raises on absolute patterns and quietly walks upward on
        # `..` segments, so both are rejected before globbing rather than after.
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            report.refused.append(pattern)
            continue
        for path in sorted(repo_root.glob(pattern)):
            if not path.is_file():
                continue
            if not contained(path, root):
                report.refused.append(str(path))
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # The FILE, not the pattern. One glob can match many files, and
                # naming the pattern leaves the operator unable to tell which of
                # them failed.
                report.unreadable.append(str(path.relative_to(repo_root)))
                continue
            matched += 1
            truncated = len(text) > MAX_STANDING_FILE_CHARS
            if truncated:
                # Said out loud in the text itself, so a reviewer reading a
                # partial file knows it is partial. Silent truncation of an
                # operator-declared file is the same lie as silent dropping.
                text = (text[:MAX_STANDING_FILE_CHARS]
                        + f"\n… [truncated at {MAX_STANDING_FILE_CHARS} chars]")
            blocks.append(ContextBlock(
                origin="standing",
                path=str(path.relative_to(repo_root)),
                symbol=path.name,
                text=text,
            ))
        if matched == 0:
            # "Matched nothing" and "nothing was configured" must not print the
            # same way. See the module docstring.
            report.empty_globs.append(pattern)

    return blocks, report
