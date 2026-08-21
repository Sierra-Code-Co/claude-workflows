"""What a diff references, and where those things are declared (T046).

Three questions, one module:

  referenced_names(diff)  what does the '+' side of this hunk mention?
  declarations(source)    what does this file declare, and what is the text?
  imports(source)         what other files does it pull names from?

Everything runs over `code_scan.blank_noncode`, so a declaration or import that
exists only inside a comment or a string literal is not one. Offsets in the mask
are offsets in the source, so patterns are matched against the mask and text is
sliced from the original.

Over-collection is safe by construction and under-collection is not: a name that
turns out to have no declaration anywhere simply yields no context, while a name
missed here is a definition the reviewer never sees. `referenced_names` is
therefore a tokeniser rather than a parser — it is allowed to be generous.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import code_scan


@dataclass(frozen=True)
class Declaration:
    name: str
    kind: str          # interface | type | class | enum | function | const | def
    text: str
    start_line: int


@dataclass(frozen=True)
class Import:
    specifier: str                       # './helper', '$lib/config', 'pkg.mod'
    # (local_name, exported_name) pairs. Both are needed and they do different
    # jobs: the LOCAL name is what appears in the diff, the EXPORTED name is
    # what to look up in the target file. `import { a as b }` makes them differ.
    bindings: tuple[tuple[str, str], ...] = field(default_factory=tuple)


_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

# Keywords never worth resolving. Not exhaustive on purpose: an unfiltered
# keyword costs one failed lookup, while a filtered-out real symbol costs the
# reviewer its definition.
_KEYWORDS = frozenset("""
abstract any as async await boolean break case catch class const constructor
continue debugger declare default delete do else enum export extends false
finally for from function get if implements import in instanceof interface is
keyof let namespace never new null number of package private protected public
readonly require return satisfies set static string super switch symbol this
throw true try type typeof undefined union unknown var void while with yield
and assert def elif except False global lambda nonlocal not None or pass raise
self True
""".split())

_TS_DECL_RE = re.compile(
    r"""^[ \t]*
    (?:export[ \t]+)?(?:default[ \t]+)?(?:declare[ \t]+)?(?:abstract[ \t]+)?
    (?:async[ \t]+)?
    (?P<kind>interface|type|class|enum|function|const|let|var)
    [ \t]*\*?[ \t]+
    (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
    """,
    re.VERBOSE | re.MULTILINE,
)

_PY_DECL_RE = re.compile(
    r"""^(?:(?:async[ \t]+)?(?P<kind>def|class)[ \t]+(?P<name>\w+)
        |(?P<cname>[A-Z_][A-Z0-9_]*)[ \t]*(?::[^=\n]+)?=)""",
    re.VERBOSE | re.MULTILINE,
)

_BLOCK_KINDS = frozenset({"interface", "class", "enum"})


def _spec(source: str, match: "re.Match[str]") -> str:
    """The module specifier, read from the SOURCE at the mask's offsets."""
    return source[match.start("spec"):match.end("spec")]


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def declarations(source: str, language: str | None) -> dict[str, Declaration]:
    """Map declared name -> Declaration, for top-level declarations only."""
    masked = code_scan.blank_noncode(source, language)
    if (language or "") == "python":
        return _python_declarations(source, masked)
    return _ts_declarations(source, masked)


def _ts_declarations(source: str, masked: str) -> dict[str, Declaration]:
    out: dict[str, Declaration] = {}
    for m in _TS_DECL_RE.finditer(masked):
        kind = m.group("kind")
        name = m.group("name")
        start = m.start()
        if kind in _BLOCK_KINDS:
            brace = masked.find("{", m.end())
            if brace == -1:
                continue
            end = code_scan.block_span(source, brace, masked)
            if end is None:
                # Unbalanced: skip rather than run to EOF. "Everything after
                # here" is not a definition, and handing it over would spend
                # the whole budget on one malformed file.
                continue
        elif kind == "function":
            # Signature only. The return TYPE is the payload; the body is
            # budget that evicts other context.
            body = masked.find("{", m.end())
            semi = masked.find(";", m.end())
            candidates = [i for i in (body, semi) if i != -1]
            end = min(candidates) if candidates else masked.find("\n", m.end())
            if end == -1:
                end = len(source)
        else:  # type | const | let | var — to the statement end
            end = _statement_end(masked, m.end())
        text = source[start:end].rstrip()
        if name not in out:
            out[name] = Declaration(name=name, kind=kind, text=text,
                                    start_line=_line_of(source, start))
    return out


def _statement_end(masked: str, from_index: int) -> int:
    """End of a `type`/`const` statement: the `;` or newline at brace depth 0."""
    depth = 0
    for i in range(from_index, len(masked)):
        c = masked[i]
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == ";" and depth <= 0:
            return i + 1
        elif c == "\n" and depth <= 0:
            return i
    return len(masked)


def _python_declarations(source: str, masked: str) -> dict[str, Declaration]:
    out: dict[str, Declaration] = {}
    for m in _PY_DECL_RE.finditer(masked):
        start = m.start()
        # Module level only: `^` with no leading whitespace in the pattern
        # already enforces it, but a nested `def` inside a masked docstring
        # would slip through if that ever changed.
        if start > 0 and masked[start - 1] != "\n":
            continue
        name = m.group("name") or m.group("cname")
        kind = m.group("kind") or "const"
        if kind in ("def", "class"):
            end = _python_signature_end(masked, m.end())
        else:
            end = masked.find("\n", m.end())
            if end == -1:
                end = len(source)
        if name not in out:
            out[name] = Declaration(name=name, kind=kind, text=source[start:end].rstrip(),
                                    start_line=_line_of(source, start))
    return out


def _python_signature_end(masked: str, from_index: int) -> int:
    """End of a def/class signature: the `:` at paren depth 0, spanning lines."""
    depth = 0
    for i in range(from_index, len(masked)):
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ":" and depth <= 0:
            return i + 1
    return len(masked)


# --- imports ------------------------------------------------------------------

_TS_IMPORT_RE = re.compile(
    r"""(?:^|\n)[ \t]*
    (?:import|export)[ \t]+
    (?:type[ \t]+)?
    (?P<clause>[^;\n]*?(?:\{[^}]*\}[^;\n]*?)?)
    \bfrom[ \t]*['"](?P<spec>[^'"]+)['"]""",
    re.VERBOSE | re.DOTALL,
)
_TS_BARE_IMPORT_RE = re.compile(r"""(?:^|\n)[ \t]*import[ \t]*['"](?P<spec>[^'"]+)['"]""")
# The clause alternation handles the PARENTHESIZED multi-line form first —
# `from x import (\n  a,\n  b,\n)` is the dominant style in this repo, and a
# line-bounded pattern silently dropped every name after the opening paren.
_PY_FROM_RE = re.compile(
    r"^[ \t]*from[ \t]+(?P<spec>[.\w]+)[ \t]+import[ \t]+"
    r"(?P<clause>\([^)]*\)|[^\n(]+)",
    re.MULTILINE,
)
# Trailing clause rather than a single specifier: `import a, b` and
# `import a as x, b` are both legal and both used to drop everything after the
# first comma.
_PY_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+(?P<clause>[\w., ]+?)[ \t]*$",
                           re.MULTILINE)


def imports(source: str, language: str | None) -> list[Import]:
    """Import edges out of this file. Comment-only imports are not edges.

    The module specifier is STRING DATA, so it is blank in the mask. Patterns
    are matched against the mask (which is what makes a commented-out import
    invisible) and the specifier is then sliced out of the SOURCE at the same
    offsets. Reading it off the mask yields a run of spaces — the first draft of
    this function did exactly that, and every import resolved to "".
    """
    masked = code_scan.blank_noncode(source, language)
    if (language or "") == "python":
        return _python_imports(source, masked)
    return _ts_imports(source, masked)


def _ts_imports(source: str, masked: str) -> list[Import]:
    out: list[Import] = []
    for m in _TS_IMPORT_RE.finditer(masked):
        clause = m.group("clause")
        bindings: list[tuple[str, str]] = []
        braced = re.search(r"\{(?P<inner>[^}]*)\}", clause, re.DOTALL)
        if braced:
            for part in braced.group("inner").split(","):
                part = part.strip().removeprefix("type ").strip()
                if not part:
                    continue
                bits = [b for b in re.split(r"\s+as\s+", part) if b]
                if len(bits) == 2:
                    bindings.append((bits[1].strip(), bits[0].strip()))
                else:
                    bindings.append((bits[0].strip(), bits[0].strip()))
            clause = clause[:braced.start()] + clause[braced.end():]
        ns = re.search(r"\*\s+as\s+(?P<ns>[A-Za-z_$][\w$]*)", clause)
        if ns:
            bindings.append((ns.group("ns"), "*"))
            clause = clause[:ns.start()] + clause[ns.end():]
        for tok in re.findall(r"[A-Za-z_$][\w$]*", clause):
            if tok not in ("from", "type"):
                bindings.append((tok, "default"))
        out.append(Import(specifier=_spec(source, m), bindings=tuple(bindings)))
    seen = {i.specifier for i in out}
    for m in _TS_BARE_IMPORT_RE.finditer(masked):
        spec = _spec(source, m)
        if spec not in seen:
            out.append(Import(specifier=spec, bindings=()))
    return out


def _python_imports(source: str, masked: str) -> list[Import]:
    out: list[Import] = []
    for m in _PY_FROM_RE.finditer(masked):
        bindings: list[tuple[str, str]] = []
        clause = source[m.start("clause"):m.end("clause")].strip().strip("()")
        for part in clause.split(","):
            part = part.strip()
            if not part or part == "*":
                continue
            bits = re.split(r"\s+as\s+", part)
            if len(bits) == 2:
                bindings.append((bits[1].strip(), bits[0].strip()))
            else:
                bindings.append((bits[0], bits[0]))
        out.append(Import(specifier=_spec(source, m), bindings=tuple(bindings)))
    for m in _PY_IMPORT_RE.finditer(masked):
        clause = source[m.start("clause"):m.end("clause")]
        for part in clause.split(","):
            part = part.strip()
            if not part:
                continue
            bits = re.split(r"\s+as\s+", part)
            spec = bits[0].strip()
            if not spec:
                continue
            local = bits[1].strip() if len(bits) == 2 else spec.split(".")[0]
            out.append(Import(specifier=spec, bindings=((local, "*"),)))
    return out


# --- what the diff references -------------------------------------------------


def referenced_names(diff_text: str, language: str | None) -> set[str]:
    """Identifiers appearing on the '+' side of a hunk.

    Generous on purpose. A name with no declaration anywhere yields no context
    and costs one failed lookup; a name missed here is a definition the reviewer
    never sees.
    """
    added: list[str] = []
    for line in diff_text.splitlines():
        # `+++ b/path` also starts with '+'. Reading it as added code pollutes
        # the set with path fragments, and a fragment that happens to match a
        # declaration pulls in context nobody asked for.
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    if not added:
        return set()
    masked = code_scan.blank_noncode("\n".join(added), language)
    return {tok for tok in _IDENT_RE.findall(masked) if tok not in _KEYWORDS}
