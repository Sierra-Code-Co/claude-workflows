"""Path filtering with CodeRabbit's semantics, and a decision you can read (T010b).

THREE DEFECTS LIVED HERE AT ONCE, and each one hid the next.

1. INERT. The `!` was never stripped, so `'!references/**'` could only match a
   path literally beginning with `!`. All nine exclusions in this repo's
   `.coderabbit.yaml` had never excluded anything.

2. INVERTED. What the old code did do was treat a BARE pattern as an exclusion —
   the opposite of CodeRabbit, where bare includes and `!` excludes. So the form
   a reader reaches for to narrow a review silently reviewed everything they
   meant to skip. Measured 2026-08-15: with 30 changed files (13 under
   `scripts/`), `path_filters: ["scripts/**"]` reviewed the 17 NON-scripts files.

3. UNREADABLE. Both of the above survived because the only feedback was a COUNT.
   "would review 17 files" is equally consistent with keeping 17 and dropping 17,
   so the number could not reveal the direction, and I published a wrong claim
   off it — describing a run as "scoped to production code" when it reviewed no
   production code at all. Hence `FilterDecision`: this module returns what was
   dropped and WHICH PATTERN dropped it, and the callers print it.

The third is the one worth generalising. A filter that reports only a magnitude
is unfalsifiable in the direction that matters.

Glob semantics are globset's, not `fnmatch`'s: `**` spans separators and may
match zero segments, `*` does not cross a separator. `fnmatch` gets `**/*.png`
wrong for a top-level `a.png`, because its `*` happily eats the `/` that the
pattern requires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


class FilterError(ValueError):
    """A pattern that cannot mean anything. Rejected loudly, never ignored."""


@dataclass(frozen=True)
class FilterDecision:
    """What the filter did, in enough detail to audit the direction."""

    kept: tuple[str, ...]
    # (path, pattern) — naming the pattern is what makes a surprising result
    # diagnosable instead of merely surprising.
    dropped: tuple[tuple[str, str], ...] = ()
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.includes or self.excludes)

    def summary(self) -> str:
        """One line naming the direction, not just the magnitude."""
        if not self.active:
            return "path_filters: none configured; all changed files reviewed"
        total = len(self.kept) + len(self.dropped)
        parts = [f"path_filters: reviewing {len(self.kept)} of {total} changed file(s)"]
        if self.includes:
            parts.append(f"include={list(self.includes)}")
        if self.excludes:
            parts.append(f"exclude={list(self.excludes)}")
        return "; ".join(parts)

    def dropped_by_pattern(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for path, pattern in self.dropped:
            out.setdefault(pattern, []).append(path)
        return out


# globset supports these; this translator does not. Escaping them literally —
# which is what the `else` branch below would do — makes `*.[jt]s` match a file
# named exactly `*.[jt]s` and nothing else, i.e. silently filter nothing. A
# pattern that quietly matches nothing is the same defect as an inert `!`, so
# unsupported syntax is rejected rather than mistranslated.
_UNSUPPORTED = {
    "[": "character classes (e.g. *.[jt]s)",
    "]": "character classes (e.g. *.[jt]s)",
    "{": "brace alternation (e.g. *.{js,ts})",
    "}": "brace alternation (e.g. *.{js,ts})",
    "\\": "backslash escapes",
}


def _reject_unsupported(pattern: str) -> None:
    # globset requires `**` to be a whole path component; `a**b` is not
    # recursive there. This translator would read it as `.*` and quietly match
    # more than globset does — a pattern behaving differently from the syntax it
    # is written in, which is the family of bug this module exists to end.
    for part in pattern.split("/"):
        if "**" in part and part != "**":
            raise FilterError(
                f"path_filters pattern {pattern!r} uses `**` inside the path "
                f"component {part!r}. `**` must be a whole component (`a/**/b`), "
                f"and this matcher does not support it elsewhere."
            )
    for ch, what in _UNSUPPORTED.items():
        if ch in pattern:
            raise FilterError(
                f"path_filters pattern {pattern!r} uses {what}, which this "
                f"matcher does not support. It would silently match nothing. "
                f"Rewrite it with *, **, and ? only, or split it into several "
                f"patterns."
            )


def _glob_to_regex(pattern: str) -> str:
    i, n, out = 0, len(pattern), []
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i >= 2:  # `**`
                if j < n and pattern[j] == "/":
                    # `**/` matches ZERO or more leading segments, which is why
                    # `**/*.png` has to match a top-level `a.png`.
                    out.append(r"(?:[^/]*/)*")
                    i = j + 1
                    continue
                out.append(r".*")
                i = j
                continue
            out.append(r"[^/]*")  # single `*` stops at a separator
            i += 1
        elif c == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "^" + "".join(out) + "$"


@lru_cache(maxsize=512)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(_glob_to_regex(pattern))


def matches(path: str, pattern: str) -> bool:
    return _compiled(pattern).match(path) is not None


def split_patterns(patterns: list[str] | tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Return (includes, excludes) with the `!` stripped from exclusions.

    CodeRabbit's convention, which is the one the config file is written in:
    a bare pattern includes, a `!`-prefixed pattern excludes.
    """
    includes: list[str] = []
    excludes: list[str] = []
    for raw in patterns:
        if not isinstance(raw, str) or not raw.strip():
            raise FilterError(f"path_filters entry is not a usable pattern: {raw!r}")
        p = raw.strip()
        if p.startswith("!"):
            body = p[1:].strip()
            if not body:
                raise FilterError(
                    "path_filters entry '!' excludes nothing; write the pattern "
                    "after the '!' or remove the entry"
                )
            _reject_unsupported(body)
            excludes.append(body)
        else:
            _reject_unsupported(p)
            includes.append(p)
    return includes, excludes


def apply_filters(paths: list[str] | tuple[str, ...],
                  patterns: list[str] | tuple[str, ...]) -> FilterDecision:
    """Keep paths matching any include (if any are declared), minus any exclude.

    With only exclusions declared — which is what every real config in this fleet
    has — the result is "everything except these", the behaviour the file always
    claimed and never had.
    """
    includes, excludes = split_patterns(patterns)
    if not includes and not excludes:
        return FilterDecision(kept=tuple(paths))

    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for p in paths:
        if includes:
            hit = next((g for g in includes if matches(p, g)), None)
            if hit is None:
                dropped.append((p, f"no include matched ({', '.join(includes)})"))
                continue
        excluded_by = next((g for g in excludes if matches(p, g)), None)
        if excluded_by is not None:
            dropped.append((p, f"!{excluded_by}"))
            continue
        kept.append(p)
    return FilterDecision(
        kept=tuple(kept), dropped=tuple(dropped),
        includes=tuple(includes), excludes=tuple(excludes),
    )
