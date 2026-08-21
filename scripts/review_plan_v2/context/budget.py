"""Fit assembled context into a bounded payload, and say what did not fit
(T049, FR-011).

Two rules, both of which exist because the alternative is a quiet lie:

  * Nothing is TRUNCATED. Half an interface still looks like an interface, and a
    reviewer reading one reasons confidently about fields that do not exist —
    manufacturing exactly the false finding this whole story closes. A block
    either arrives whole or is dropped and named.

  * Operator-declared standing files outrank derived context. The operator named
    those files; the harness inferred the rest. Evicting the declaration in
    favour of the inference inverts whose judgment wins.

Within a tier, smaller blocks are placed first: at a fixed budget that admits
strictly more definitions, and the ones it excludes are the ones whose absence
is easiest to notice.
"""
from __future__ import annotations

from ._types import ContextBlock

DEFAULT_BUDGET_CHARS = 40_000

_TIER = {"standing": 0, "same-file": 1, "imported": 2}


def fit(blocks: list[ContextBlock], limit_chars: int = DEFAULT_BUDGET_CHARS
        ) -> tuple[list[ContextBlock], list[ContextBlock]]:
    """Return (kept, dropped). Order within `kept` follows the input order."""
    ordered = sorted(
        enumerate(blocks),
        key=lambda pair: (_TIER.get(pair[1].origin, 9), pair[1].chars, pair[0]),
    )
    kept_indices: set[int] = set()
    used = 0
    for index, block in ordered:
        if used + block.chars <= limit_chars:
            kept_indices.add(index)
            used += block.chars
    kept = [b for i, b in enumerate(blocks) if i in kept_indices]
    dropped = [b for i, b in enumerate(blocks) if i not in kept_indices]
    return kept, dropped
