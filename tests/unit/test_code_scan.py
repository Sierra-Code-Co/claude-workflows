"""The source scanner that context extraction is built on (T046).

Everything US5 does rests on locating a declaration inside a file, which means
knowing which characters are code and which are commentary or string data. This
repo already owns a measured lesson about getting that wrong: gold-set entry G5
is a regex comment-stripper that deleted a 33,904-character span of live code
because a `/*` inside a LINE comment opened a block the regex closed 765 lines
later at the `*/` inside a regex literal (mtg-cube-ai#2110, FR-006).

So this scanner does not strip. `blank_noncode` returns a string of the SAME
LENGTH with non-code characters replaced by spaces, which makes every offset in
the masked text an offset in the original — nothing can be deleted, because
nothing is removed. The tests below are derived from the scanner's own state
machine (one per state, plus each transition that can be entered wrongly)
rather than from the one bug that happened to be famous.
"""
from __future__ import annotations

import pytest
from review_plan_v2.context import code_scan


def _mask(src: str, language: str = "typescript") -> str:
    return code_scan.blank_noncode(src, language)


# --- the length invariant, which is the whole design -------------------------


@pytest.mark.parametrize("language", ["typescript", "python"])
@pytest.mark.parametrize("src", [
    "const a = 1;",
    "// just a comment\n",
    "/* block */ const a = 1;",
    "const s = 'text with // and /* inside';",
    "`template ${a + 1} literal`",
    "def f():\n    '''doc'''\n    return 1\n",
    "",
    "\n\n\n",
])
def test_masking_never_changes_length(src, language):
    """The property that makes deletion impossible. G5's stripper could not have
    had this property; that is precisely what let it lose code."""
    assert len(_mask(src, language)) == len(src)


@pytest.mark.parametrize("language", ["typescript", "python"])
def test_masking_preserves_newlines(language):
    """Line numbers must survive, or every offset reported from the mask points
    at the wrong line in the original."""
    src = "a\nb\n// c\nd\n"
    assert _mask(src, language).count("\n") == src.count("\n")


# --- one case per scanner state ----------------------------------------------


def test_a_line_comment_is_blanked():
    assert _mask("const a = 1; // secret\n").rstrip() == "const a = 1;"


def test_a_block_comment_is_blanked():
    masked = _mask("const /* hidden */ a = 1;")
    assert "hidden" not in masked
    assert "const" in masked and "a = 1;" in masked


def test_a_string_body_is_blanked_but_the_quotes_survive():
    """Quotes stay so that a declaration scan can still see the token boundary;
    the CONTENTS go, because that is where lookalike syntax hides."""
    masked = _mask("const a = 'interface Fake { x: 1 }';")
    assert "interface Fake" not in masked
    assert masked.count("'") == 2


def test_a_template_literal_is_blanked_but_its_interpolation_is_code():
    """`${...}` is executable and can contain a declaration reference, so it must
    NOT be masked. A scanner that treats the whole template as one string loses
    real code."""
    masked = _mask("const a = `LITERALTEXT ${describeThrown(e)} MORELITERAL`;")
    assert "describeThrown(e)" in masked
    assert "LITERALTEXT" not in masked
    assert "MORELITERAL" not in masked


def test_nested_template_interpolation_returns_to_string_state():
    """Needles are multi-character on purpose: single letters collide with the
    surrounding `const`, which made the first draft of this test fail against a
    correct scanner."""
    masked = _mask("const a = `OUTERA ${ `INNERA ${refname} INNERB` } OUTERB`;")
    assert "refname" in masked
    for literal in ("OUTERA", "OUTERB", "INNERA", "INNERB"):
        assert literal not in masked, f"{literal} is string data and must be blanked"


# --- the G5 shapes, in both directions ---------------------------------------


def test_a_block_comment_opener_inside_a_line_comment_does_not_open_a_block():
    """G5 exactly, and the shape that is live in the proving ground. Everything
    after the line comment must remain code."""
    src = (
        "// delegate to /api/workflow/tools/* which enforces ownership\n"
        "export interface ThrownDescription { errMessage: string; }\n"
    )
    masked = _mask(src)
    assert "ThrownDescription" in masked, (
        "a `/*` inside a line comment swallowed the declaration below it — "
        "this is mtg-cube-ai#2110 reproduced in the scanner"
    )


def test_a_regex_literal_does_not_disturb_the_code_after_it():
    """Weaker than its original name promised, and renamed to match what it
    checks. A reviewer of this file pointed out that with no `/*` open, the `*/`
    inside this regex cannot close anything — so the old name claimed a G5 case
    the body never reached. The real closer case is the test below."""
    src = "const re = /\\s*\\n+\\s*/g;\nexport interface Real { a: string; }\n"
    masked = _mask(src)
    assert "Real" in masked


def test_the_whole_g5_span_survives_both_halves_together():
    """mtg-cube-ai#2110 end to end: the deleted span must remain code.

    The incident needed both halves at once — a `/*` inside a LINE comment
    opened a fake block, and a `*/` inside a REGEX LITERAL closed it 765 lines
    later, deleting the 33,904 characters between them along with six live
    console calls.

    Neither delimiter is real in context, so a correct scanner opens nothing and
    the entire span stays live. The first draft of this test asserted the
    opposite — that the text between them was commented out — which is the
    STRIPPER's behaviour, not the language's. It failed, correctly, and is
    reproduced here as the positive statement instead: every one of these lines
    is code.
    """
    src = (
        "// delegate to /api/workflow/tools/* which enforces ownership\n"
        "const insideTheDeletedSpan = 1;\n"
        "const re = /\\s*\\n+\\s*/g;\n"
        "export interface Real { a: string; }\n"
    )
    masked = _mask(src)
    for survivor in ("insideTheDeletedSpan", "const re", "Real"):
        assert survivor in masked, (
            f"{survivor} was swallowed — a fake block comment opened at the "
            "`/*` inside the line comment, which is #2110's mechanism"
        )
    assert "delegate to" not in masked, "the line comment itself is not code"


def test_a_regex_literal_containing_a_comment_opener_is_string_data():
    src = "const re = /\\/\\*/;\nexport interface Real { a: string; }\n"
    masked = _mask(src)
    assert "Real" in masked


def test_division_is_not_mistaken_for_a_regex_literal():
    """The anti-vacuous control for the regex heuristic. Treating every `/` as a
    regex opener would blank the rest of any file containing arithmetic."""
    src = "const ratio = total / count;\nexport interface Real { a: string; }\n"
    masked = _mask(src)
    assert "Real" in masked
    assert "count" in masked


def test_an_escaped_quote_does_not_end_a_string():
    masked = _mask("const a = 'it\\'s'; export interface Real { a: string; }")
    assert "Real" in masked


# --- python states ------------------------------------------------------------


def test_a_python_hash_comment_is_blanked():
    masked = _mask("x = 1  # def fake():\n", "python")
    assert "def fake" not in masked
    assert "x = 1" in masked


def test_a_python_triple_quoted_docstring_is_blanked():
    src = 'def f():\n    """def not_a_real_def(): pass"""\n    return 1\n'
    masked = _mask(src, "python")
    assert "not_a_real_def" not in masked
    assert "def f():" in masked
    assert "return 1" in masked


def test_a_python_hash_inside_a_string_is_not_a_comment():
    """The needle must be on the SAME line as the `#`.

    The first version put `def real()` on the next line, where a `#`-comment
    would never have reached it — a line comment blanks to end of line. It could
    not fail, which a reviewer of this file spotted. `KEEPME` sits after the
    closing quote, so it survives only if the string ended where it should.
    """
    src = "x = '# not a comment' + KEEPME\n"
    masked = _mask(src, "python")
    assert "KEEPME" in masked
    assert "not a comment" not in masked


def test_a_double_slash_in_python_is_floor_division_not_a_comment():
    """Language dispatch, asserted rather than assumed: `//` is an operator in
    Python and a comment in TypeScript, and one scanner serves both."""
    src = "x = 7 // 2\ndef real(): pass\n"
    masked = _mask(src, "python")
    assert "def real" in masked
    assert "2" in masked


# --- brace matching on top of the mask ----------------------------------------


def test_block_span_ignores_braces_inside_strings():
    src = "interface A { name: 'a}b'; other: string; }\nconst after = 1;"
    start = src.index("{")
    end = code_scan.block_span(src, start, _mask(src))
    assert src[start:end].endswith("}")
    assert "other" in src[start:end]
    assert "after" not in src[start:end]


def test_block_span_handles_nesting():
    src = "interface A { inner: { deep: string }; last: number; }\nconst after = 1;"
    start = src.index("{")
    end = code_scan.block_span(src, start, _mask(src))
    assert "last" in src[start:end]
    assert "after" not in src[start:end]


def test_an_unbalanced_block_reports_no_span_rather_than_running_to_eof():
    """A truncated or malformed file must not silently yield "everything after
    here" as the definition — that is a quiet way to blow the context budget on
    garbage."""
    src = "interface A { name: string;\n"
    assert code_scan.block_span(src, src.index("{"), _mask(src)) is None


# --- interpolation nesting, found by review ----------------------------------


def test_a_brace_inside_a_string_inside_an_interpolation_does_not_close_it():
    """The bug the mode stack fixes.

    The first scanner located the end of `${...}` with a bare brace counter, so
    the `}` inside the string argument closed the interpolation early and every
    offset after it was wrong. Reported by review, not by recall.
    """
    masked = _mask('const a = `x ${foo("}")} y`; export interface Real { b: string; }')
    assert "Real" in masked, "the interpolation ended early and desynchronised the scan"
    assert "foo(" in masked, "the interpolation is code and must survive"


def test_a_comment_inside_an_interpolation_is_still_a_comment():
    masked = _mask("const a = `x ${/* HIDDEN */ value} y`;")
    assert "HIDDEN" not in masked
    assert "value" in masked


def test_deeply_nested_templates_do_not_blow_the_stack():
    """The old implementation recursed once per interpolation."""
    src = "const a = " + "`x ${" * 200 + "v" + "} y`" * 200 + ";"
    masked = _mask(src)
    assert len(masked) == len(src)


def test_block_span_rejects_a_negative_index():
    """`str.find` returns -1 on a miss, and `masked[-1]` inspects the LAST
    character — answering a question about the end of the file."""
    src = "interface A { name: string; }"
    assert code_scan.block_span(src, -1, _mask(src)) is None
