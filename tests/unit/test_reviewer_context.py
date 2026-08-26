"""Assembling the context a reviewer is given (T045, T046, T049).

Three sources, one budget:

  standing   operator-declared files attached to every call        (#18, T045)
  same-file  declarations referenced by the hunk but outside it    (T046)
  imported   declarations one hop away through an import edge      (#19, T046)

The ordering of that list is the design. The famous framing of #19 is "include
imported files", but gold-set entry G6 — the `describeThrown` false positive
this closes — was raised against a declaration in the SAME FILE, ten lines above
the hunk. Cross-file resolution alone would not have prevented it, so same-file
resolution is not an optimisation here; it is half the fix.

FR-011 governs the budget: context dropped to fit MUST be reported. A reviewer
silently given less than the harness believes it gave is a reviewer whose
findings cannot be interpreted, and "we sent the definition" would then be a
claim about intent rather than about what happened.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest
from review_plan_v2 import context
from review_plan_v2.context import budget as budget_mod
from review_plan_v2.context import related, standing
from review_plan_v2.types import FileChange

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLD_SET = json.loads((REPO_ROOT / "tests" / "fixtures" / "gold_set_20260813.json").read_text())
CORPUS = REPO_ROOT / GOLD_SET["corpus_root"]


def _chunk(path: str, diff_body: str, language: str = "typescript") -> FileChange:
    return FileChange(
        path=path,
        is_binary=False,
        is_renamed_from=None,
        added_lines=(),
        diff_text=f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{diff_body}",
        language=language,
    )


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A small TS/Python repo with the import shapes that must resolve."""
    (tmp_path / "web" / "src" / "lib" / "server").mkdir(parents=True)
    (tmp_path / "web" / "src" / "lib" / "server" / "describe-thrown.ts").write_text(
        "export interface ThrownDescription {\n"
        "\terrName: string;\n"
        "\terrMessage: string;\n"
        "}\n\n"
        "export function describeThrown(e: unknown): ThrownDescription {\n"
        "\treturn { errName: 'E', errMessage: String(e) };\n"
        "}\n"
    )
    (tmp_path / "web" / "src" / "lib" / "shared.ts").write_text(
        "export const SHARED_LIMIT = 42;\n"
    )
    (tmp_path / "web" / "src" / "lib" / "server" / "index.ts").write_text(
        "export const BARREL_TOKEN = 'barrel';\n"
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "helpers.py").write_text("MAX_COMMANDERS = 2\n\n\ndef bound(n):\n    return n\n")
    return tmp_path


# --- same-file resolution: the half that actually closes G6 -------------------


def test_a_declaration_referenced_by_the_hunk_but_above_it_is_included(repo):
    """G6, reproduced. The hunk changes the function body; the interface that
    refutes the false claim is outside the window."""
    chunk = _chunk(
        "web/src/lib/server/describe-thrown.ts",
        "+\treturn { errName: 'E', errMessage: String(e) } satisfies ThrownDescription;\n",
    )
    blocks, _ = related.gather(chunk, repo)
    texts = {b.symbol: b.text for b in blocks}
    assert "ThrownDescription" in texts
    assert "errMessage" in texts["ThrownDescription"]
    assert all(b.origin == "same-file" for b in blocks if b.symbol == "ThrownDescription")


def test_a_declaration_already_visible_in_the_hunk_is_not_repeated(repo):
    """Budget spent restating what the reviewer is already reading is budget
    taken from context it does not have."""
    chunk = _chunk(
        "web/src/lib/server/describe-thrown.ts",
        "+export interface ThrownDescription {\n+\terrName: string;\n+}\n",
    )
    blocks, _ = related.gather(chunk, repo)
    assert "ThrownDescription" not in {b.symbol for b in blocks}


def test_an_unreferenced_declaration_is_not_included(repo):
    """Anti-vacuous control. "Attach the whole file" passes every test above and
    exhausts the budget on the first large file it meets."""
    chunk = _chunk("web/src/lib/server/describe-thrown.ts", "+const unrelated = 1;\n")
    assert [b for b in related.gather(chunk, repo)[0] if b.symbol == "ThrownDescription"] == []


def test_a_type_referenced_only_by_another_definition_is_pulled_in(repo):
    """One transitive hop WITHIN the file. The hunk names `describeThrown`; its
    return type is what a return-shape claim turns on, and nothing in the diff
    mentions `ThrownDescription` by name."""
    chunk = _chunk("web/src/lib/server/consumer.ts", "+const d = describeThrown(e);\n")
    (repo / "web" / "src" / "lib" / "server" / "consumer.ts").write_text(
        "import { describeThrown } from './describe-thrown';\n"
        "const d = describeThrown(e);\n"
    )
    blocks, _ = related.gather(chunk, repo)
    symbols_found = {b.symbol for b in blocks}
    assert "describeThrown" in symbols_found
    assert "ThrownDescription" in symbols_found, (
        "the imported function's return TYPE was not resolved, which is exactly "
        "the fact G6 got wrong"
    )


# --- import resolution --------------------------------------------------------


@pytest.mark.parametrize("specifier, expected_symbol", [
    ("./describe-thrown", "describeThrown"),
    ("../shared", "SHARED_LIMIT"),
    ("$lib/shared", "SHARED_LIMIT"),
])
def test_an_import_specifier_resolves(repo, specifier, expected_symbol):
    path = "web/src/lib/server/consumer.ts"
    (repo / path).write_text(
        f"import {{ {expected_symbol} }} from '{specifier}';\nconst x = {expected_symbol};\n"
    )
    chunk = _chunk(path, f"+const x = {expected_symbol};\n")
    blocks, _ = related.gather(chunk, repo, aliases={"$lib": "web/src/lib"})
    assert expected_symbol in {b.symbol for b in blocks}


def test_a_directory_import_resolves_through_its_index_file(repo):
    path = "web/src/lib/consumer.ts"
    (repo / path).write_text(
        "import { BARREL_TOKEN } from './server';\nconst x = BARREL_TOKEN;\n"
    )
    chunk = _chunk(path, "+const x = BARREL_TOKEN;\n")
    blocks, _ = related.gather(chunk, repo)
    assert "BARREL_TOKEN" in {b.symbol for b in blocks}


def test_a_python_import_resolves(repo):
    path = "pkg/consumer.py"
    (repo / path).write_text(
        "from .helpers import MAX_COMMANDERS\n\nlimit = MAX_COMMANDERS\n"
    )
    chunk = _chunk(path, "+limit = MAX_COMMANDERS\n", language="python")
    blocks, _ = related.gather(chunk, repo)
    assert "MAX_COMMANDERS" in {b.symbol for b in blocks}


def test_a_third_party_import_is_external_not_unresolved(repo):
    """`typescript` and `vitest` are not in the repo and never will be. Filing
    them as failures would make the unresolved list noise, and a noisy list is
    one nobody reads."""
    path = "web/src/lib/server/consumer.ts"
    (repo / path).write_text("import ts from 'typescript';\nconst x = ts.foo;\n")
    chunk = _chunk(path, "+const x = ts.foo;\n")
    _, report = related.gather(chunk, repo)
    assert report.unresolved == []
    assert "typescript" in report.external


def test_a_local_looking_import_that_does_not_resolve_is_reported(repo):
    """The blind spot must be visible. A relative import that resolves to
    nothing means the reviewer is reasoning about a symbol whose definition the
    harness silently failed to find."""
    path = "web/src/lib/server/consumer.ts"
    (repo / path).write_text("import { gone } from './missing-file';\nconst x = gone;\n")
    chunk = _chunk(path, "+const x = gone;\n")
    _, report = related.gather(chunk, repo)
    assert "./missing-file" in report.unresolved


def test_a_relative_specifier_escaping_the_repo_is_refused(repo, tmp_path):
    """Containment is checked on the RESOLVED path, not the literal.

    The first draft of this test imported `../../../../../../../etc/passwd` and
    passed with the containment check DELETED — because that many `..` segments
    land on a path that does not exist, so the specifier was rejected as
    unresolved and never reached the check at all. It asserted the right outcome
    by the wrong route, which is this spec's own defect class.

    The target below is a file that genuinely exists and genuinely sits outside
    the repository, so only containment can refuse it.
    """
    outside = tmp_path.parent / "outside-secret.ts"
    outside.write_text("export const secret = 'do not exfiltrate';\n")
    path = "web/src/lib/server/consumer.ts"
    # Computed, not hand-counted. A literal `'../' * 4` lands one level short of
    # the target, which resolves to a path INSIDE the repo that does not exist —
    # so the specifier is rejected as unresolved and containment is never
    # reached. That is how the first draft of this test passed with the check
    # deleted.
    specifier = os.path.relpath(outside.with_suffix(""), (repo / path).parent)
    (repo / path).write_text(
        f"import {{ secret }} from '{specifier}';\nconst x = secret;\n"
    )
    chunk = _chunk(path, "+const x = secret;\n")
    blocks, report = related.gather(chunk, repo)

    assert blocks == [], "a definition from outside the repository was attached"
    assert report.refused, "the escape was neither attached nor reported"
    assert not any("do not exfiltrate" in b.text for b in blocks)


def test_a_symlink_pointing_outside_the_repo_is_refused(repo, tmp_path):
    """The reason containment resolves symlinks. A link INSIDE the repo passes
    every literal-path check ever written and reads a file outside it."""
    outside = tmp_path.parent / "linked-secret.ts"
    outside.write_text("export const secret = 'do not exfiltrate';\n")
    link = repo / "web" / "src" / "lib" / "server" / "linked.ts"
    link.symlink_to(outside)

    path = "web/src/lib/server/consumer.ts"
    (repo / path).write_text("import { secret } from './linked';\nconst x = secret;\n")
    chunk = _chunk(path, "+const x = secret;\n")
    blocks, report = related.gather(chunk, repo)

    assert not any("do not exfiltrate" in b.text for b in blocks)
    assert report.refused


def test_a_missing_source_file_is_not_an_exception(repo):
    """The diff can name a file that was DELETED in this change. Reading it must
    degrade to "no context", not abort the review."""
    chunk = _chunk("web/src/lib/server/deleted.ts", "+const x = 1;\n")
    blocks, report = related.gather(chunk, repo)
    assert blocks == []
    assert report.unreadable == ["web/src/lib/server/deleted.ts"]


# --- standing context (T045, #18) ---------------------------------------------


def test_standing_files_are_attached(repo):
    (repo / "CONVENTIONS.md").write_text("Never log a raw caught value.\n")
    blocks, report = standing.gather(repo, ["CONVENTIONS.md"])
    assert len(blocks) == 1
    assert "Never log a raw caught value" in blocks[0].text
    assert blocks[0].origin == "standing"
    assert report.empty_globs == []


def test_a_standing_glob_matching_nothing_is_reported(repo):
    """A scope that matches nothing looks identical to a clean result — the
    exact defect class this portfolio exists to close, and one this repo has
    already hit four times in lint/scan configs. Silence here means the operator
    believes standing context is attached when none is."""
    _, report = standing.gather(repo, ["docs/*.md"])
    assert report.empty_globs == ["docs/*.md"]


@pytest.mark.parametrize("pattern", ["../../../etc/passwd", "/etc/passwd"])
def test_a_standing_glob_leaving_the_repo_is_refused_by_name(repo, pattern):
    """Both escape shapes, each asserted on `refused` SPECIFICALLY.

    The first version asserted `report.empty_globs or report.refused`, which a
    non-matching glob satisfies through the wrong branch — it would have passed
    with the refusal deleted. Reported by review of this change, and it is the
    same "true for an unrelated reason" defect the mutation proof exists to
    catch; this one slipped through because no mutation targeted the branch.
    """
    blocks, report = standing.gather(repo, [pattern])
    assert report.refused == [pattern], f"{pattern} was not refused by name"
    assert blocks == []


def test_a_standing_symlink_pointing_outside_the_repo_is_refused(repo, tmp_path):
    """A link INSIDE the repo passes every literal-path check and reads a file
    outside it. This is why containment resolves before comparing."""
    outside = tmp_path.parent / "standing-secret.md"
    outside.write_text("EXFILTRATED\n")
    (repo / "linked.md").symlink_to(outside)
    blocks, report = standing.gather(repo, ["*.md"])
    assert not any("EXFILTRATED" in b.text for b in blocks)
    assert report.refused


def test_a_standing_file_at_exactly_the_cap_is_not_truncated(repo):
    """Boundary, both sides. Truncating a file that fits would silently shorten
    operator-declared context; not truncating one that does not fit would let a
    single file consume the budget."""
    exact = "x" * standing.MAX_STANDING_FILE_CHARS
    (repo / "exact.md").write_text(exact)
    (repo / "over.md").write_text("y" * (standing.MAX_STANDING_FILE_CHARS + 1))

    by_name = {b.symbol: b for b in standing.gather(repo, ["exact.md", "over.md"])[0]}
    assert by_name["exact.md"].text == exact
    assert "truncated" not in by_name["exact.md"].text
    assert "truncated" in by_name["over.md"].text, (
        "an over-length standing file was truncated SILENTLY; a reviewer reading "
        "a partial file must be told it is partial"
    )


def test_standing_globs_resolve_to_stable_order(repo):
    (repo / "a.md").write_text("A\n")
    (repo / "b.md").write_text("B\n")
    first = [b.path for b in standing.gather(repo, ["*.md"])[0]]
    second = [b.path for b in standing.gather(repo, ["*.md"])[0]]
    assert first == second == sorted(first)


# --- budget (T049, FR-011) ----------------------------------------------------


def _block(symbol: str, size: int, origin: str = "imported"):
    return context.ContextBlock(origin=origin, path=f"{symbol}.ts", symbol=symbol, text="x" * size)


def test_everything_fits_when_the_budget_allows():
    blocks = [_block("A", 100), _block("B", 100)]
    kept, dropped = budget_mod.fit(blocks, limit_chars=10_000)
    assert kept == blocks
    assert dropped == []


def test_what_does_not_fit_is_dropped_and_named():
    kept, dropped = budget_mod.fit([_block("Big", 5_000), _block("Small", 10)], limit_chars=1_000)
    assert [b.symbol for b in kept] == ["Small"]
    assert [b.symbol for b in dropped] == ["Big"]


def test_standing_context_outranks_derived_context():
    """The operator declared the standing files by name. Evicting those in
    favour of something the harness inferred inverts whose judgment wins."""
    kept, _ = budget_mod.fit(
        [_block("Derived", 900, origin="imported"), _block("Declared", 900, origin="standing")],
        limit_chars=1_000,
    )
    assert [b.symbol for b in kept] == ["Declared"]


def test_a_single_block_larger_than_the_whole_budget_is_dropped_not_truncated():
    """Truncating a declaration produces text that LOOKS like a definition and
    is not one — a reviewer reading half an interface reasons about fields that
    do not exist. Dropping it is honest; truncating it manufactures a lie."""
    kept, dropped = budget_mod.fit([_block("Huge", 50_000)], limit_chars=1_000)
    assert kept == []
    assert [b.symbol for b in dropped] == ["Huge"]


def test_the_rendered_context_reports_its_drops():
    kept, dropped = budget_mod.fit([_block("Big", 5_000), _block("Small", 10)], limit_chars=1_000)
    rendered = context.render_for_prompt(kept, dropped)
    assert "Big" in rendered, "a dropped definition must be NAMED, not counted"
    assert "not included" in rendered.lower() or "dropped" in rendered.lower()


def test_rendering_nothing_produces_nothing():
    """An empty context block would otherwise add a header promising context and
    then deliver none, which reads to a model as "there is nothing to know"."""
    assert context.render_for_prompt([], []) == ""


# --- SC-005, the deterministic half (T050) ------------------------------------


def test_the_gold_set_corpus_delivers_the_declaration_that_refutes_g6():
    """SC-005's checkable half.

    Whether the reviewer still WRITES the false finding is a question about a
    live model and is recorded in audit/sc005.md. What is asserted here is the
    thing the harness controls: the declaration that makes the claim false is in
    the payload. Before this change it was not, in any run, for any model.
    """
    chunk = _chunk(
        "web/src/lib/server/describe-thrown.ts",
        "+export function describeThrown(e: unknown): ThrownDescription {\n",
    )
    blocks, _ = related.gather(chunk, CORPUS)
    rendered = context.render_for_prompt(*budget_mod.fit(blocks, limit_chars=40_000))
    assert "errMessage" in rendered
    assert "errName" in rendered

# --- reported by review of this change ---------------------------------------


def test_budget_drops_are_recorded_on_the_report_for_the_operator(repo):
    """FR-011 has two audiences and they were being told different things.

    The reviewer's prompt named the dropped definitions from the start. The
    OPERATOR — the only party who can raise `context_budget_chars` — saw
    nothing, because `assemble` never put the drops on the report that feeds the
    run banner. Caught by review, not by the mutation sweep, which only checked
    the prompt side.
    """
    (repo / "big.md").write_text("x" * 5_000)
    (repo / "small.md").write_text("y" * 10)
    _, dropped, report = context.assemble(
        _chunk("web/src/lib/server/describe-thrown.ts", "+const a = 1;\n"),
        repo, always_include=["big.md", "small.md"], limit_chars=1_000,
    )
    assert dropped, "nothing was dropped, so this test proves nothing"
    assert any("big.md" in entry for entry in report.dropped)
    assert report.has_gaps()


def test_the_context_section_marks_its_contents_as_untrusted(repo):
    """Repository file content is now interpolated into the reviewer prompt, and
    on a pull request that content is author-controlled. An instruction-shaped
    line inside a quoted file must not read as an instruction."""
    rendered = context.render_for_prompt(
        [context.ContextBlock(origin="standing", path="a.md", symbol="a.md", text="hello")], []
    )
    assert "UNTRUSTED FILE CONTENT" in rendered
    assert "BEGIN a.md" in rendered and "END a.md" in rendered


def test_a_relevant_import_beyond_the_edge_cap_is_still_resolved(repo):
    """The cap bounds WORK; it must not decide which symbol the reviewer learns
    about. Slicing before filtering made a file's 13th import invisible."""
    server = repo / "web" / "src" / "lib" / "server"
    for i in range(20):
        (server / f"noise{i}.ts").write_text(f"export const NOISE{i} = {i};\n")
    (server / "wanted.ts").write_text("export const WANTED_LATE = 'here';\n")
    lines = [f"import {{ NOISE{i} }} from './noise{i}';" for i in range(20)]
    lines.append("import { WANTED_LATE } from './wanted';")
    (server / "consumer.ts").write_text("\n".join(lines) + "\nconst x = WANTED_LATE;\n")

    chunk = _chunk("web/src/lib/server/consumer.ts", "+const x = WANTED_LATE;\n")
    blocks, _ = related.gather(chunk, repo)
    assert "WANTED_LATE" in {b.symbol for b in blocks}

