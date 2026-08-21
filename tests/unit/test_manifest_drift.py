"""Vendored-file drift classification (T052, T054).

The question is "will the next `specify init` clobber work I care about", and
the four answers are NOT interchangeable:

  pristine   hash matches       -> update is safe
  modified   differs on disk    -> update destroys your edit
  missing    recorded, absent   -> state unknown
  untracked  manifest never saw it -> CANNOT be classified at all

T052 asks specifically that a locally modified file be reported distinctly from
a clean one, and the tests below are weighted toward the ways "no drift" can be
printed by a run that established nothing — an unreadable manifest, an empty
file list, a file that could not be read.

The manifest tracked ONE file out of 23 when this was written, and reported no
drift. That is the state these tests exist to make unreachable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest

import speckit_drift

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def repo(tmp_path):
    """A miniature vendored tree with a manifest."""
    (tmp_path / ".specify/templates").mkdir(parents=True)
    (tmp_path / ".specify/integrations").mkdir(parents=True)
    (tmp_path / ".claude/skills/vendored-skill").mkdir(parents=True)

    tpl = tmp_path / ".specify/templates/plan-template.md"
    tpl.write_text("upstream content\n")
    skill = tmp_path / ".claude/skills/vendored-skill/SKILL.md"
    skill.write_text('---\nname: vendored-skill\nsource: "templates/commands/x.md"\n---\nbody\n')

    manifest = {
        "integration": "speckit", "version": "0.5.0",
        "files": {
            ".specify/templates/plan-template.md": speckit_drift.sha256_of(tpl),
            ".claude/skills/vendored-skill/SKILL.md": speckit_drift.sha256_of(skill),
        },
    }
    (tmp_path / speckit_drift.MANIFEST_PATH).write_text(json.dumps(manifest))
    return tmp_path


def test_an_untouched_tree_is_clean(repo):
    """Anti-vacuous control. Without it, a classifier that called everything
    modified would satisfy every failure test below."""
    report = speckit_drift.scan(repo)
    assert report.is_clean
    assert len(report.pristine) == 2
    assert report.modified == []


def test_a_locally_modified_file_is_reported_DISTINCTLY(repo):
    """T052's actual requirement: `modified` must not read like `pristine`."""
    (repo / ".specify/templates/plan-template.md").write_text("I edited this\n")
    report = speckit_drift.scan(repo)
    assert report.modified == [".specify/templates/plan-template.md"]
    assert ".specify/templates/plan-template.md" not in report.pristine
    assert not report.is_clean

    rendered = speckit_drift.render(report)
    assert "[MODIFIED]" in rendered
    assert "WILL OVERWRITE" in rendered, (
        "the report must state the CONSEQUENCE; 'differs' alone does not tell "
        "the reader their edit is about to be destroyed"
    )


def test_a_deleted_file_is_missing_not_pristine(repo):
    (repo / ".specify/templates/plan-template.md").unlink()
    report = speckit_drift.scan(repo)
    assert report.missing == [".specify/templates/plan-template.md"]
    assert not report.is_clean


def test_a_file_the_manifest_never_saw_is_UNTRACKED_and_not_clean(repo):
    """The state that made the real manifest useless: 1 file tracked, 22 not,
    and a clean report. An unclassifiable file is not a passing file."""
    new = repo / ".specify/templates/newly-vendored.md"
    new.write_text("arrived in a later spec-kit release\n")
    report = speckit_drift.scan(repo)
    assert report.untracked == [".specify/templates/newly-vendored.md"]
    assert not report.is_clean
    assert "CANNOT be determined" in speckit_drift.render(report)


def test_an_unreadable_manifest_classifies_NOTHING_as_clean(repo):
    """The worst possible failure for this script, so it gets its own test.

    A corrupt manifest means zero files were verified. Returning "clean" there
    would be a drift checker that reports success precisely when it is broken.
    """
    (repo / speckit_drift.MANIFEST_PATH).write_text("{ not json")
    report = speckit_drift.scan(repo)
    assert report.pristine == []
    assert not report.is_clean
    assert len(report.untracked) == 2


def test_an_empty_file_list_is_not_clean(repo):
    """`all([])` is True — the shape that lets an empty rule set report complete
    coverage of nothing. Here the manifest parses but tracks no files."""
    (repo / speckit_drift.MANIFEST_PATH).write_text(json.dumps(
        {"integration": "speckit", "version": "0.5.0", "files": {}}))
    report = speckit_drift.scan(repo)
    assert not report.is_clean
    assert len(report.untracked) == 2


# --- provenance: ours vs upstream --------------------------------------------


def test_a_skill_without_a_source_field_is_NOT_vendored(repo):
    """`review-plan-v2` is locally authored. Reporting it as "vendored, will be
    clobbered" would be false, and a report that cries wolf on a file nobody
    will ever overwrite is one people stop reading — costing the real ones."""
    ours = repo / ".claude/skills/our-own-skill"
    ours.mkdir(parents=True)
    (ours / "SKILL.md").write_text("---\nname: our-own-skill\n---\nno source field\n")
    report = speckit_drift.scan(repo)
    assert report.untracked == [], "a locally authored skill was treated as vendored"
    assert report.is_clean


def test_a_skill_WITH_a_source_field_is_vendored(repo):
    """Anti-vacuous companion: the provenance rule must still catch real ones."""
    other = repo / ".claude/skills/speckit-clarify"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text(
        '---\nname: speckit-clarify\nsource: "templates/commands/clarify.md"\n---\nbody\n')
    report = speckit_drift.scan(repo)
    assert report.untracked == [".claude/skills/speckit-clarify/SKILL.md"]


def test_source_is_read_from_frontmatter_not_from_prose(repo):
    """A `source:` mentioned in body text is not provenance."""
    ours = repo / ".claude/skills/prose-mention"
    ours.mkdir(parents=True)
    (ours / "SKILL.md").write_text(
        "---\nname: prose-mention\n---\n" + "\n" * 20 + "source: not-frontmatter\n")
    assert speckit_drift.source_of(ours / "SKILL.md") is None


# --- the local-edit trap ------------------------------------------------------


def test_a_declared_local_edit_is_surfaced_even_though_it_hashes_pristine(repo):
    """The trap I walked into rebuilding the real manifest.

    Rebuilding from disk baselines whatever is there, so a file already edited
    locally becomes "pristine" and the report goes quiet about the one file most
    at risk. `local_edits` records the human judgement that hashing destroyed.
    """
    manifest = json.loads((repo / speckit_drift.MANIFEST_PATH).read_text())
    manifest["local_edits"] = [".specify/templates/plan-template.md"]
    (repo / speckit_drift.MANIFEST_PATH).write_text(json.dumps(manifest))

    report = speckit_drift.scan(repo)
    assert report.local_edits == [".specify/templates/plan-template.md"]
    rendered = speckit_drift.render(report)
    assert "[LOCAL EDIT]" in rendered
    assert "WILL overwrite" in rendered
    assert "an update will not clobber local work" not in rendered, (
        "the summary contradicted the banner directly above it"
    )


def test_a_rebuild_preserves_declared_local_edits(repo):
    """`local_edits` is a human judgement no amount of hashing can recover once
    the edit is baselined, so a rebuild must carry it forward, not recompute."""
    manifest = json.loads((repo / speckit_drift.MANIFEST_PATH).read_text())
    manifest["local_edits"] = [".specify/templates/plan-template.md"]
    (repo / speckit_drift.MANIFEST_PATH).write_text(json.dumps(manifest))

    rebuilt = speckit_drift.build_manifest(repo, "0.6.0")
    assert rebuilt["local_edits"] == [".specify/templates/plan-template.md"]


# --- the real repo ------------------------------------------------------------


def test_the_shipped_manifest_covers_the_whole_vendored_surface():
    """The state T053 closed: 1 file tracked out of 23, reported as no drift.

    Run against the REAL repo, because a manifest that validates in a fixture
    while the shipped one covers 4% of the surface is the gap that mattered.
    """
    report = speckit_drift.scan(REPO_ROOT)
    assert report.untracked == [], f"vendored files outside the manifest: {report.untracked}"
    assert report.checked_count >= 20, (
        f"only {report.checked_count} files checked — the manifest has shrunk "
        f"back toward the 1-file state this task existed to fix"
    )
