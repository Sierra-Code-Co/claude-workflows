"""Locate code inside a source file without deleting anything.

Every context feature in US5 needs to answer "where is this symbol declared?",
and answering it means telling code apart from commentary and string data. This
repo owns a measured lesson about the naive way to do that: gold-set entry G5 is
a regex comment-stripper that removed a 33,904-character span of LIVE code
because a `/*` inside a line comment opened a block the regex closed 765 lines
later at the `*/` inside a regex literal (mtg-cube-ai#2110, FR-006).

The defect there was not the regex. It was the deletion: once a span is gone,
every offset after it is wrong and nothing downstream can notice. So this module
never removes a character. `blank_noncode` returns a string of the SAME LENGTH
with non-code replaced by spaces, so offsets into the mask are offsets into the
original and the two can always be read together — search the mask, slice the
source.

The scanner is a character-level state machine, not a pattern. That is what lets
it distinguish `/` as division from `/` as a regex opener, which is the exact
distinction G5's second half turned on.
"""
from __future__ import annotations

# Tokens after which a `/` opens a REGEX LITERAL rather than dividing. This is
# the standard lexer heuristic: a regex can only appear where a value is
# expected, so the preceding token decides. Getting it wrong in the permissive
# direction blanks the rest of a file containing arithmetic; getting it wrong in
# the strict direction is how G5's `*/` escaped its literal.
_REGEX_PRECEDING_CHARS = set("(,=:[!&|?{};+-*%~^<>")
_REGEX_PRECEDING_WORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "do", "else", "yield", "await", "case", "throw",
})

_PYTHON_LIKE = frozenset({"python"})


def _prev_significant(masked: list[str], i: int) -> tuple[str, str]:
    """Return (last non-space char before i, the word ending at that char)."""
    j = i - 1
    while j >= 0 and masked[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return "", ""
    ch = masked[j]
    if not (ch.isalnum() or ch == "_" or ch == "$"):
        return ch, ""
    k = j
    while k >= 0 and (masked[k].isalnum() or masked[k] in "_$"):
        k -= 1
    return ch, "".join(masked[k + 1:j + 1])


def blank_noncode(text: str, language: str | None) -> str:
    """Same-length copy of `text` with comments and string bodies as spaces.

    Newlines are preserved so line numbers survive. Quote and brace characters
    are preserved so structure remains scannable; only the CONTENTS of strings
    and comments are blanked, because that is where lookalike syntax hides.

    `${...}` inside a template literal is executable and stays code.
    """
    is_python = (language or "") in _PYTHON_LIKE
    out: list[str] = []
    i = 0
    n = len(text)

    # An explicit mode stack rather than recursion. The first version recursed
    # on the `${...}` span and located its end with a bare brace counter, so a
    # `}` inside a string or comment WITHIN the interpolation closed it early —
    # `` `a ${foo("}")} b` `` desynchronised the rest of the file. Here an
    # interpolation simply re-enters CODE, which already handles strings,
    # comments, regexes and nested templates, and `}` at depth 0 returns to the
    # template. It is also unbounded-recursion-free by construction.
    mode = "code"
    stack: list[tuple[str, int]] = []
    brace_depth = 0
    #: A template nested past this depth is pathological input, not source.
    MAX_NESTING = 64

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if mode == "template":
            if ch == "\\" and i + 1 < n:
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            if ch == "`":
                out.append("`")
                i += 1
                mode, brace_depth = stack.pop() if stack else ("code", 0)
                continue
            if ch == "$" and nxt == "{":
                # Interpolation is CODE.
                out.append("$")
                out.append("{")
                i += 2
                if len(stack) < MAX_NESTING:
                    stack.append(("template", brace_depth))
                    mode, brace_depth = "code", 0
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        # --- comments ---------------------------------------------------
        if not is_python and ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if not is_python and ch == "/" and nxt == "*":
            out.append(" ")
            out.append(" ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append(" ")
                out.append(" ")
                i += 2
            continue
        if is_python and ch == "#":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue

        # --- python triple-quoted strings -------------------------------
        if is_python and (text[i:i + 3] == '"""' or text[i:i + 3] == "'''"):
            quote = text[i:i + 3]
            out.extend(quote)
            i += 3
            while i < n and text[i:i + 3] != quote:
                if text[i] == "\\" and i + 1 < n:
                    out.append(" ")
                    out.append(" ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.extend(quote)
                i += 3
            continue

        # --- ordinary strings -------------------------------------------
        if ch in "'\"":
            quote = ch
            out.append(quote)
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    out.append(" ")
                    out.append(" ")
                    i += 2
                    continue
                # An unterminated string must not eat the rest of the file.
                if text[i] == "\n":
                    break
                out.append(" ")
                i += 1
            if i < n and text[i] == quote:
                out.append(quote)
                i += 1
            continue

        # --- template literals ------------------------------------------
        if not is_python and ch == "`":
            out.append("`")
            i += 1
            stack.append(("code", brace_depth))
            mode, brace_depth = "template", 0
            continue

        # --- regex literals ---------------------------------------------
        if not is_python and ch == "/":
            prev_char, prev_word = _prev_significant(out, len(out))
            opens_regex = (
                prev_char == ""
                or prev_char in _REGEX_PRECEDING_CHARS
                or prev_word in _REGEX_PRECEDING_WORDS
            )
            if opens_regex:
                out.append("/")
                i += 1
                in_class = False
                while i < n and text[i] != "\n":
                    if text[i] == "\\" and i + 1 < n:
                        out.append(" ")
                        out.append(" ")
                        i += 2
                        continue
                    if text[i] == "[":
                        in_class = True
                    elif text[i] == "]":
                        in_class = False
                    elif text[i] == "/" and not in_class:
                        break
                    out.append(" ")
                    i += 1
                if i < n and text[i] == "/":
                    out.append("/")
                    i += 1
                continue

        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            if brace_depth == 0 and stack and stack[-1][0] == "template":
                out.append("}")
                i += 1
                mode, brace_depth = stack.pop()
                continue
            brace_depth = max(0, brace_depth - 1)
        out.append(ch)
        i += 1

    masked = "".join(out)
    # The scanner appends one char per consumed char in every branch, but an
    # off-by-one in any of them would silently shift every offset downstream.
    # Assert rather than trust: this invariant is the module's whole contract.
    if len(masked) != len(text):
        raise AssertionError(
            f"blank_noncode changed length ({len(text)} -> {len(masked)}); "
            "every offset derived from the mask would be wrong"
        )
    return masked


def block_span(text: str, open_index: int, masked: str | None = None,
               language: str | None = None) -> int | None:
    """Index just past the `}` matching the `{` at `open_index`.

    Returns None when the braces do not balance. A malformed or truncated file
    must not yield "everything after here" as a definition — that silently
    spends the whole context budget on garbage.
    """
    if masked is None:
        masked = blank_noncode(text, language)
    # `open_index < 0` matters: callers get it from `str.find`, which returns
    # -1 on a miss, and `masked[-1]` would then inspect the LAST character —
    # answering a question about the end of the file.
    if open_index < 0 or open_index >= len(masked) or masked[open_index] != "{":
        return None
    depth = 0
    for i in range(open_index, len(masked)):
        c = masked[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None
