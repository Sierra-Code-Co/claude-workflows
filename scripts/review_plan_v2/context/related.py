"""Definitions for symbols the diff references but does not show (T046, #19).

Two hops, in this order:

  1. the SAME FILE, outside the hunk window
  2. one import edge away

The order matters and the first hop is not an optimisation. The famous framing
of issue #19 is "include imported files", but gold-set entry G6 — the
`describeThrown` false positive this closes — was raised against a declaration
in the same file, ten lines above the hunk. Cross-file resolution alone would
have left it firing.

Every failure mode here degrades to "no context" rather than to an exception: a
deleted file, an unreadable one, a specifier pointing outside the repository.
The review must still happen. What must NOT happen is failing silently, so each
of those outcomes is recorded on the report and printed by the caller.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import contained
from ..types import FileChange
from . import symbols
from ._types import ContextBlock

# Probed in order for a bare TS/JS specifier.
_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".svelte", ".d.ts")
_TS_INDEXES = ("index.ts", "index.tsx", "index.js", "index.jsx")

_MAX_IMPORT_EDGES = 12
_MAX_BLOCKS = 24


@dataclass
class ContextReport:
    #: local-looking specifiers that resolved to nothing — a real blind spot
    unresolved: list[str] = field(default_factory=list)
    #: bare specifiers owned by a package manager; NOT a failure
    external: list[str] = field(default_factory=list)
    #: files named by the diff that could not be read (deleted, binary, perms)
    unreadable: list[str] = field(default_factory=list)
    #: standing globs that matched no file (T045)
    empty_globs: list[str] = field(default_factory=list)
    #: paths refused by the containment check
    refused: list[str] = field(default_factory=list)
    #: definitions evicted to fit the budget, as "path :: symbol" (FR-011).
    #: These are named in the reviewer's prompt already; recording them here is
    #: what puts them in front of the OPERATOR, who is the one who can raise
    #: context_budget_chars. Review of this change caught that the two audiences
    #: were being told different things.
    dropped: list[str] = field(default_factory=list)

    def merge(self, other: "ContextReport") -> "ContextReport":
        for name in ("unresolved", "external", "unreadable", "empty_globs", "refused", "dropped"):
            getattr(self, name).extend(getattr(other, name))
        return self

    def has_gaps(self) -> bool:
        return bool(self.unresolved or self.unreadable or self.empty_globs
                    or self.refused or self.dropped)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


#: Re-exported under the original private name so the call sites below read
#: unchanged. The body moved to `review_plan_v2.paths` when T005g/T005h needed
#: the same predicate: five hand-written copies of a security check is how one
#: of them ends up subtly different with nothing to catch it.
_contained = contained


def resolve_module(specifier: str, from_path: str, repo_root: Path,
                   aliases: dict[str, str] | None = None,
                   language: str | None = None) -> tuple[Path | None, str]:
    """Resolve an import specifier to a file. Returns (path, disposition).

    disposition is one of: "ok", "external", "unresolved", "refused".
    """
    aliases = aliases or {}
    from_dir = (repo_root / from_path).parent

    if (language or "") == "python":
        return _resolve_python(specifier, from_dir, repo_root)

    if specifier.startswith("."):
        base = from_dir / specifier
    else:
        # Longest-prefix alias match, so `$lib/server` beats `$lib` when both
        # are declared.
        matched = None
        for prefix in sorted(aliases, key=len, reverse=True):
            if specifier == prefix or specifier.startswith(prefix + "/"):
                matched = prefix
                break
        if matched is None:
            # Bare specifier with no alias: owned by a package manager. Not a
            # failure, and filing it as one makes the unresolved list noise.
            return None, "external"
        base = repo_root / aliases[matched] / specifier[len(matched):].lstrip("/")

    found = _probe(base)
    if found is None:
        return None, "unresolved"
    if not _contained(found, repo_root):
        return None, "refused"
    return found, "ok"


def _probe(base: Path) -> Path | None:
    if base.is_file():
        return base
    for suffix in _TS_SUFFIXES:
        candidate = base.with_name(base.name + suffix)
        if candidate.is_file():
            return candidate
    for index in _TS_INDEXES:
        candidate = base / index
        if candidate.is_file():
            return candidate
    return None


def _resolve_python(specifier: str, from_dir: Path, repo_root: Path) -> tuple[Path | None, str]:
    if specifier.startswith("."):
        ups = len(specifier) - len(specifier.lstrip("."))
        base = from_dir
        for _ in range(ups - 1):
            base = base.parent
        tail = specifier[ups:].replace(".", os.sep)
        candidates = [base / f"{tail}.py", base / tail / "__init__.py"] if tail else [base / "__init__.py"]
    else:
        tail = specifier.replace(".", os.sep)
        candidates = [
            repo_root / f"{tail}.py",
            repo_root / tail / "__init__.py",
            repo_root / "src" / f"{tail}.py",
            repo_root / "src" / tail / "__init__.py",
        ]
    for candidate in candidates:
        if candidate.is_file():
            if not _contained(candidate, repo_root):
                return None, "refused"
            return candidate, "ok"
    # A dotted specifier with no local file is an installed package.
    return None, "unresolved" if specifier.startswith(".") else "external"


def gather(chunk: FileChange, repo_root: Path | str,
           aliases: dict[str, str] | None = None) -> tuple[list[ContextBlock], ContextReport]:
    """Definitions the reviewer needs and the hunk does not show."""
    repo_root = Path(repo_root)
    report = ContextReport()
    blocks: list[ContextBlock] = []

    source = _read(repo_root / chunk.path)
    if source is None:
        report.unreadable.append(chunk.path)
        return blocks, report

    wanted = symbols.referenced_names(chunk.diff_text, chunk.language)
    if not wanted:
        return blocks, report

    own = symbols.declarations(source, chunk.language)
    visible = chunk.diff_text

    def take(decl: symbols.Declaration, origin: str, path: str) -> None:
        if len(blocks) >= _MAX_BLOCKS:
            return
        if any(b.symbol == decl.name and b.path == path for b in blocks):
            return
        blocks.append(ContextBlock(origin=origin, path=path, symbol=decl.name, text=decl.text))

    # --- hop 1: same file, outside the hunk ---------------------------------
    for name in sorted(wanted):
        decl = own.get(name)
        if decl is None:
            continue
        # Restating what the reviewer is already reading spends budget that
        # other context needs.
        if decl.text.splitlines()[0].strip() in visible:
            continue
        take(decl, "same-file", chunk.path)

    # --- hop 2: one import edge --------------------------------------------
    # Filter by relevance BEFORE capping. Slicing first meant a file with more
    # than _MAX_IMPORT_EDGES imports could drop the one edge the diff actually
    # references — the cap is there to bound work, not to pick which symbol the
    # reviewer gets to know about.
    relevant = [
        (imp, [(lo, ex) for lo, ex in imp.bindings if lo in wanted])
        for imp in symbols.imports(source, chunk.language)
    ]
    relevant = [(imp, binds) for imp, binds in relevant if binds][:_MAX_IMPORT_EDGES]
    for imp, locals_wanted in relevant:
        target, disposition = resolve_module(
            imp.specifier, chunk.path, repo_root, aliases, chunk.language
        )
        if disposition == "external":
            report.external.append(imp.specifier)
            continue
        if disposition == "refused":
            report.refused.append(imp.specifier)
            report.unresolved.append(f"{imp.specifier} (resolves outside the repository)")
            continue
        if target is None:
            report.unresolved.append(imp.specifier)
            continue
        target_source = _read(target)
        if target_source is None:
            report.unreadable.append(str(target.relative_to(repo_root)))
            continue
        target_language = chunk.language
        target_decls = symbols.declarations(target_source, target_language)
        rel = str(target.relative_to(repo_root))
        for _local, exported in locals_wanted:
            decl = target_decls.get(exported)
            if decl is None:
                continue
            take(decl, "imported", rel)
            # One transitive hop WITHIN the target file. A function's return
            # TYPE is what a return-shape claim turns on, and nothing in the
            # diff mentions it by name — which is exactly how G6 was written.
            for token in symbols.referenced_names("+" + decl.text.replace("\n", "\n+"),
                                                  target_language):
                nested = target_decls.get(token)
                if nested is not None and nested.name != decl.name:
                    take(nested, "imported", rel)

    return blocks, report
