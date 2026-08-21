"""One containment predicate, used everywhere a path arrives from outside (T005g/T005h).

By the time these two tasks were reached, this repo held THREE hand-rolled
copies of the same six-line check — `context/related.py::_contained`,
an inline block in `context/standing.py::gather`, and another inside
`context/rounds.py::anchor_hash` — and was about to grow a fourth and a fifth.
Each copy was written correctly. That is exactly the condition under which
duplication is dangerous: nothing fails today, so nothing signals when the
fourth copy is written slightly differently, and a security predicate that
disagrees with itself across call sites is worse than one that is merely
absent, because four of the five sites keep working and vouch for the fifth.

The two rules this module encodes are both mistakes already made in this fleet:

  * `Path("/repo") / "/etc/passwd"` is `/etc/passwd`. pathlib DISCARDS the left
    operand when the right is absolute, so joining an untrusted string to a
    root is not containment — it is a no-op the moment the string is absolute.
    Found in `rounds.py` against reviewer-supplied paths.
  * containment must be judged on the RESOLVED path. `../../../../etc/passwd`
    holds no suspicious token once normalised, and a symlink that lives inside
    the repo can point anywhere at all. A textual check passes both.

`is_relative_to` is deliberately not used: it compares lexically, so it answers
True for a repo-internal symlink whose target is outside. The whole reason this
check exists is the case that method gets wrong.
"""
from __future__ import annotations

from pathlib import Path

#: Path segments that can walk upward. `..` only — note that `..foo` is an
#: ordinary filename and must NOT be refused, which is what separates this from
#: a substring search for "..".
_TRAVERSAL = ".."

#: Rejected outright in a repo-relative path. A backslash is a SEPARATOR on
#: Windows, so `..\..\x` contains no `..` segment when split on "/" and sailed
#: through the first draft of this module; on POSIX it is a legal (if bizarre)
#: filename character, and no path in this repo uses one. Refusing it costs
#: nothing real and removes a platform-dependent bypass rather than documenting
#: it. Reported by review; confirmed by measurement before fixing.
_ALWAYS_REJECT = "\\"


def contained(candidate: Path | str, root: Path | str) -> bool:
    """True if `candidate` lies inside `root` once symlinks are resolved.

    A candidate equal to the root counts as contained. Anything that cannot be
    resolved at all counts as NOT contained, since "cannot tell" must never
    resolve in favour of access.

    The exception tuple is wider than it looks like it needs to be, and both
    additions were measured rather than assumed:

      * `ValueError` — `resolve()` raises it, not OSError, for a path holding an
        embedded NUL. The first draft caught only OSError, so `safe_join` broke
        its own `Path | None` contract and raised on hostile input.
      * `RuntimeError` — historically raised on symlink loops. On 3.14 a loop
        instead resolves to the lexical path, so a loop INSIDE the root reads as
        contained and the caller's own read fails harmlessly. Caught anyway,
        because that behaviour is a Python implementation detail this module
        should not depend on. Note the docstring no longer claims loops return
        False: it did, and the claim was untrue on the interpreter in use.
    """
    try:
        resolved = Path(candidate).resolve()
        root_resolved = Path(root).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return resolved == root_resolved or root_resolved in resolved.parents


def is_safe_relative(raw: str) -> bool:
    """True if `raw` is a non-empty relative path with no upward segments.

    A cheap textual pre-check for values that have not touched the filesystem
    yet — schema-adjacent validation, where refusing early gives a better error
    than a resolve() that silently lands somewhere unexpected. It is NOT a
    substitute for `contained`: it cannot see symlinks. Both layers are needed,
    and each catches cases the other cannot.
    """
    if not raw or raw.startswith("/") or _ALWAYS_REJECT in raw:
        return False
    # Split on "/" rather than using Path.parts, because Path("a/../b").parts
    # keeps ".." but Path("").parts is empty and Path("a//b") collapses — the
    # normalisation is helpful for reading and unhelpful for validating.
    return _TRAVERSAL not in raw.split("/")


def safe_join(root: Path | str, raw: str) -> Path | None:
    """Join `raw` under `root`, or None if it escapes by any route.

    Both layers, in the order that keeps the error useful: reject the textual
    forms first, then resolve and confirm. Callers get None and decide whether
    that is a refusal to report or a hard error — this module never decides for
    them, because "refuse quietly" is the wrong answer in every case here.
    """
    if not is_safe_relative(raw):
        return None
    joined = Path(root) / raw
    if not contained(joined, root):
        return None
    return joined
