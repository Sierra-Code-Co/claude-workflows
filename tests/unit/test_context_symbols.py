"""Declaration and import extraction (T046).

The reviewer is shown one file's diff. When that diff references a symbol whose
declaration is somewhere else — another file, or the same file outside the hunk
window — the reviewer either guesses or says nothing. It guessed: gold-set entry
G6 asserts `describeThrown` returns `{ name, message }`, which is wrong, and the
declaration that refutes it sat ten lines above the hunk.

Note what that means about the fix. The famous framing is "include imported
files", but G6's declaration was in the SAME FILE. Cross-file resolution alone
would not have prevented it. Both hops are tested here.

Extraction runs over `code_scan.blank_noncode`, so a declaration that appears
only inside a comment or a string is not a declaration. That case is tested
rather than assumed, because it is the one an author writing positives from
recall never produces.
"""
from __future__ import annotations

import pytest
from review_plan_v2.context import symbols

TS_SOURCE = """\
// A file shaped like the one G6 was raised against.
import { helper } from './helper';
import type { Cfg } from '$lib/config';
import defaultThing, { other as renamed } from '../shared/thing';
import * as ns from './ns';

export interface ThrownDescription {
\terrName: string;
\terrMessage: string;
\terrCode: string | null;
}

export type Level = 'info' | 'warn';

export const MAX_LEN = 300;

export function describeThrown(e: unknown): ThrownDescription {
\treturn { errName: 'Error', errMessage: String(e), errCode: null };
}

export default async function main(): Promise<void> {}

export class Widget {
\tready = false;
}

export enum Mode {
\tOn,
\tOff,
}

// export interface CommentedOut { gone: string; }
const decoy = 'export interface InsideAString { x: 1 }';
"""


@pytest.fixture(scope="module")
def ts_decls() -> dict:
    return symbols.declarations(TS_SOURCE, "typescript")


# --- typescript declarations --------------------------------------------------


@pytest.mark.parametrize("name", [
    "ThrownDescription", "Level", "MAX_LEN", "describeThrown", "main", "Widget", "Mode",
])
def test_a_typescript_declaration_is_found(ts_decls, name):
    assert name in ts_decls, f"{name} was not extracted"


@pytest.mark.parametrize("name", ["CommentedOut", "InsideAString"])
def test_a_declaration_that_exists_only_in_a_comment_or_string_is_not_one(ts_decls, name):
    """The anti-vacuous half, and the reason extraction runs over the mask.

    A regex over raw source finds both of these, and the resulting "definition"
    handed to a reviewer would be text the compiler never sees.
    """
    assert name not in ts_decls


def test_an_interface_body_is_captured_whole(ts_decls):
    """The G6 fix in one assertion: the field names are what refute the claim.
    A signature line alone (`export interface ThrownDescription {`) carries none
    of the information the false finding got wrong."""
    text = ts_decls["ThrownDescription"].text
    for field in ("errName", "errMessage", "errCode"):
        assert field in text
    assert text.rstrip().endswith("}")


def test_a_function_captures_its_signature_and_stops_before_the_body(ts_decls):
    """The return TYPE is the payload. The body is budget spent on nothing —
    and on a large function it is budget that evicts other context."""
    text = ts_decls["describeThrown"].text
    assert "describeThrown(e: unknown): ThrownDescription" in text
    assert "String(e)" not in text, "the body was included; that is wasted budget"


def test_a_type_alias_captures_its_right_hand_side(ts_decls):
    assert "'info' | 'warn'" in ts_decls["Level"].text


def test_a_const_captures_its_value(ts_decls):
    assert "300" in ts_decls["MAX_LEN"].text


def test_declarations_record_their_line_number(ts_decls):
    line = ts_decls["ThrownDescription"].start_line
    assert TS_SOURCE.splitlines()[line - 1].startswith("export interface ThrownDescription")


def test_an_unterminated_block_is_skipped_not_run_to_end_of_file():
    src = "export interface Broken {\n\tname: string;\n"
    assert "Broken" not in symbols.declarations(src, "typescript")


# --- python declarations ------------------------------------------------------

PY_SOURCE = '''\
"""Module docstring mentioning def not_real(): pass."""
import os
from .sibling import helper
from pkg.mod import thing as renamed

MAX_COMMANDERS = 2


def describe_thrown(e, *, verbose=False):
    """Doc."""
    def nested():
        return 1
    return nested()


class Widget:
    def method(self):
        pass
'''


@pytest.fixture(scope="module")
def py_decls() -> dict:
    return symbols.declarations(PY_SOURCE, "python")


@pytest.mark.parametrize("name", ["MAX_COMMANDERS", "describe_thrown", "Widget"])
def test_a_python_declaration_is_found(py_decls, name):
    assert name in py_decls


@pytest.mark.parametrize("name", ["nested", "method", "not_real"])
def test_a_nested_or_commented_python_declaration_is_not_module_level(py_decls, name):
    """`nested` and `method` are real code but not module-level API, and
    `not_real` exists only inside the module docstring."""
    assert name not in py_decls


def test_a_python_signature_spans_its_full_parameter_list(py_decls):
    assert "verbose=False" in py_decls["describe_thrown"].text


# --- imports ------------------------------------------------------------------


@pytest.fixture(scope="module")
def ts_imports() -> list:
    return symbols.imports(TS_SOURCE, "typescript")


def _by_specifier(imports: list, specifier: str):
    matches = [i for i in imports if i.specifier == specifier]
    assert matches, f"no import of {specifier!r} among {[i.specifier for i in imports]}"
    return matches[0]


def test_a_named_import_records_its_names(ts_imports):
    imp = _by_specifier(ts_imports, "./helper")
    assert ("helper", "helper") in imp.bindings


def test_a_type_only_import_is_still_an_import(ts_imports):
    """`import type` is erased at runtime and is exactly the form that carries
    the declaration a return-shape claim turns on."""
    imp = _by_specifier(ts_imports, "$lib/config")
    assert ("Cfg", "Cfg") in imp.bindings


def test_a_renamed_import_records_both_local_and_exported_names(ts_imports):
    """Both halves are needed and they are used for different things: the LOCAL
    name is what appears in the diff, the EXPORTED name is what to look up in
    the target file. Recording only one makes the other lookup fail."""
    imp = _by_specifier(ts_imports, "../shared/thing")
    assert ("renamed", "other") in imp.bindings
    assert ("defaultThing", "default") in imp.bindings


def test_a_namespace_import_is_recorded(ts_imports):
    imp = _by_specifier(ts_imports, "./ns")
    assert ("ns", "*") in imp.bindings


def test_a_multiline_import_clause_is_parsed():
    src = "import {\n  alpha,\n  beta as gamma,\n} from './multi';\n"
    imp = _by_specifier(symbols.imports(src, "typescript"), "./multi")
    assert ("alpha", "alpha") in imp.bindings
    assert ("gamma", "beta") in imp.bindings


def test_a_re_export_is_an_import_edge():
    src = "export { thing } from './re-exported';\n"
    imp = _by_specifier(symbols.imports(src, "typescript"), "./re-exported")
    assert ("thing", "thing") in imp.bindings


def test_an_import_inside_a_comment_is_not_an_import():
    src = "// import { ghost } from './nowhere';\nconst a = 1;\n"
    assert symbols.imports(src, "typescript") == []


@pytest.fixture(scope="module")
def py_imports() -> list:
    return symbols.imports(PY_SOURCE, "python")


def test_a_python_relative_import_is_recorded(py_imports):
    imp = _by_specifier(py_imports, ".sibling")
    assert ("helper", "helper") in imp.bindings


def test_a_python_aliased_import_records_both_names(py_imports):
    imp = _by_specifier(py_imports, "pkg.mod")
    assert ("renamed", "thing") in imp.bindings


# --- what the diff references -------------------------------------------------


def test_referenced_names_come_from_added_lines_only():
    diff = (
        "diff --git a/x.ts b/x.ts\n"
        "--- a/x.ts\n"
        "+++ b/x.ts\n"
        "@@ -1,2 +1,2 @@\n"
        "-const gone = removedSymbol();\n"
        " const kept = contextSymbol();\n"
        "+const fresh = describeThrown(e);\n"
    )
    names = symbols.referenced_names(diff, "typescript")
    assert "describeThrown" in names
    assert "removedSymbol" not in names, "a symbol only on the '-' side is not referenced"


def test_the_diff_header_is_not_mistaken_for_added_code():
    """`+++ b/path` starts with a plus. Reading it as an added line pollutes the
    reference set with path fragments, and a path fragment that happens to match
    a declaration pulls in irrelevant context."""
    diff = "--- a/uniquename.ts\n+++ b/uniquename.ts\n@@ -1 +1 @@\n+const a = 1;\n"
    assert "uniquename" not in symbols.referenced_names(diff, "typescript")


def test_language_keywords_are_not_treated_as_referenced_symbols():
    diff = "+++ b/x.ts\n@@ -1 +1 @@\n+export const a = function () { return null; };\n"
    names = symbols.referenced_names(diff, "typescript")
    for kw in ("export", "const", "function", "return", "null"):
        assert kw not in names


# --- reported by review of this change ----------------------------------------


def test_a_multiline_parenthesized_python_import_is_parsed():
    """The dominant style in this repo, and the line-bounded pattern dropped
    every name after the opening paren — silently, so the symbols simply never
    resolved. Reported by review; no test covered it."""
    src = "from pkg.helpers import (\n    alpha,\n    beta as gamma,\n)\n"
    imp = _by_specifier(symbols.imports(src, "python"), "pkg.helpers")
    assert ("alpha", "alpha") in imp.bindings
    assert ("gamma", "beta") in imp.bindings


def test_a_python_import_of_several_modules_records_all_of_them():
    """`import a, b` is legal and the old pattern kept only `a`."""
    specs = {i.specifier for i in symbols.imports("import os, sys\n", "python")}
    assert {"os", "sys"} <= specs
