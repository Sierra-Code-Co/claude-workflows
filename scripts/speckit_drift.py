"""Classify vendored spec-kit files as pristine, modified, missing or untracked (T054).

The problem this closes: `./setup.sh` re-runs `specify init`, which OVERWRITES
vendored files. A local edit to one of them is destroyed on the next update, and
nothing tells you beforehand — the update reports success either way. The
manifest exists to make that predictable, and it tracked **1 file out of 23**.

Four states, and the fourth is the one that matters:

  pristine   hash matches the manifest — an update is safe
  modified   on disk and DIFFERENT — an update will clobber your edit
  missing    in the manifest, absent on disk — deleted or moved
  untracked  a vendored-looking file the manifest has never heard of

`untracked` is not a rounding error. A file the manifest does not cover cannot
be classified at all, so calling it "no drift" is the exact silent-degradation
this portfolio exists to close (FR-004). It is counted, named, and it makes the
run non-clean.

DELIBERATELY DETERMINISTIC. Prior art for this — Cole Medin's
`rules-check-drift` (see research.md T051) — asks a MODEL whether a prose rule
is still true, which is right for that question. Ours is "do these bytes match",
which constitution Principle III forbids routing to a reviewer: sha256 answers
it in milliseconds with no false positives, and a reviewer would answer it
sometimes.

What was adopted from that skill is its reporting instinct: a "checked, still
true" line, so "no drift found" is never printable by a run that examined
nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

#: Directories whose contents come from upstream spec-kit and are overwritten by
#: `specify init`. A file here is a candidate for drift; a file anywhere else is
#: ours and is not this script's business.
VENDORED_ROOTS = (
    ".specify/templates",
    ".specify/scripts",
    ".claude/skills",
)

#: Never drift-checked: caches and generated artefacts that legitimately change.
_IGNORED_SUFFIXES = (".pyc",)
_IGNORED_PARTS = frozenset({"__pycache__", ".DS_Store"})

#: Under `.claude/skills/`, provenance decides. A SKILL.md with a `source:`
#: field came from upstream and `specify init` will overwrite it; one WITHOUT
#: is ours — `review-plan-v2` is locally authored, and reporting it as
#: "vendored, will be clobbered" would be false. A report that cries wolf on a
#: file nobody will ever overwrite is one people stop reading, which costs the
#: nine genuine ones. T053 asks for exactly this: read provenance from the
#: existing frontmatter rather than assuming by directory.
_PROVENANCE_ROOT = ".claude/skills"

MANIFEST_PATH = ".specify/integrations/speckit.manifest.json"


@dataclass
class DriftReport:
    pristine: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    #: Files the manifest RECORDS as carrying deliberate local edits. They hash
    #: pristine (the manifest baselined them) but `specify init` will still
    #: overwrite them, so they are the ones most at risk and the least visible.
    local_edits: list[str] = field(default_factory=list)
    manifest_version: str = "unknown"

    @property
    def is_clean(self) -> bool:
        """Clean means EVERY vendored file was classified and none had drifted.

        `untracked` counts against clean on purpose. An unclassifiable file is
        not a passing file; it is a file nobody checked.
        """
        return not (self.modified or self.missing or self.untracked)

    @property
    def checked_count(self) -> int:
        return len(self.pristine) + len(self.modified) + len(self.missing)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def source_of(path: Path) -> str | None:
    """→ the `source:` frontmatter value, or None if the file declares none.

    Read from the first few lines only: frontmatter is at the top by
    definition, and a `source:` appearing later in prose is not provenance.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = [next(f, "") for _ in range(12)]
    except OSError:
        return None
    for line in head:
        stripped = line.strip()
        if stripped.startswith("source:"):
            return stripped.partition(":")[2].strip().strip('"\'') or None
    return None


def _is_vendored_candidate(rel: str, root: Path | None = None) -> bool:
    parts = Path(rel).parts
    if any(p in _IGNORED_PARTS for p in parts):
        return False
    if rel.endswith(_IGNORED_SUFFIXES):
        return False
    if not any(rel.startswith(vr + "/") for vr in VENDORED_ROOTS):
        return False
    # Under .claude/skills, a file is vendored only if it says where it came
    # from. Without a repo root to read the file we cannot tell, so we say YES —
    # over-reporting is loud and gets corrected; under-reporting is silent.
    if rel.startswith(_PROVENANCE_ROOT + "/") and root is not None:
        return source_of(root / rel) is not None
    return True


def scan(repo_root: Path | str, manifest_path: str = MANIFEST_PATH) -> DriftReport:
    """Compare the vendored surface against the manifest. Never raises on data."""
    root = Path(repo_root)
    report = DriftReport()

    try:
        manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable manifest classifies NOTHING. Reporting that as clean
        # would be the worst possible failure for this script, so every
        # vendored file becomes untracked and the run is not clean.
        manifest = {}

    report.manifest_version = str(manifest.get("version", "unknown"))
    recorded: dict[str, str] = manifest.get("files") or {}
    if not isinstance(recorded, dict):
        recorded = {}
    declared_local = manifest.get("local_edits")
    report.local_edits = sorted(declared_local) if isinstance(declared_local, list) else []

    for rel, expected in sorted(recorded.items()):
        path = root / rel
        if not path.is_file():
            report.missing.append(rel)
            continue
        try:
            actual = sha256_of(path)
        except OSError:
            # Unreadable is not pristine. "Could not check" must never fall
            # into the passing bucket.
            report.missing.append(rel)
            continue
        (report.pristine if actual == expected else report.modified).append(rel)

    on_disk = set()
    for vendored_root in VENDORED_ROOTS:
        base = root / vendored_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _is_vendored_candidate(rel, root):
                on_disk.add(rel)
    report.untracked = sorted(on_disk - set(recorded))
    return report


def render(report: DriftReport) -> str:
    """Operator-facing report. Names everything; counts only the clean ones."""
    lines: list[str] = [
        f"spec-kit drift check (manifest version {report.manifest_version})",
        "",
    ]
    if report.modified:
        lines.append(
            "[MODIFIED] these vendored files differ from the manifest. "
            "`./setup.sh` re-runs `specify init` and WILL OVERWRITE them — move "
            "the change into an overlay before updating:"
        )
        lines += [f"  - {p}" for p in report.modified]
        lines.append("")
    if report.missing:
        lines.append(
            "[MISSING] recorded in the manifest but not on disk (deleted, moved, "
            "or unreadable). Their state is unknown, not clean:"
        )
        lines += [f"  - {p}" for p in report.missing]
        lines.append("")
    if report.untracked:
        lines.append(
            "[UNTRACKED] vendored-looking files the manifest has never recorded, "
            "so drift CANNOT be determined for them. This is absent coverage, "
            "not a clean result — re-run the manifest builder:"
        )
        lines += [f"  - {p}" for p in report.untracked]
        lines.append("")

    if report.local_edits:
        lines.append(
            "[LOCAL EDIT] these hash pristine because the manifest was rebuilt "
            "WITH the edit in place — but they diverge from upstream and "
            "`specify init` will still overwrite them. Rebuilding a manifest "
            "from disk baselines whatever is there, which is precisely how a "
            "local edit becomes invisible:"
        )
        lines += [f"  - {p}" for p in report.local_edits]
        lines.append("")

    # Adopted from rules-check-drift: say what was VERIFIED, so "no drift" is
    # never printable by a run that examined nothing.
    lines.append(
        f"checked {report.checked_count} vendored file(s); "
        f"{len(report.pristine)} pristine, {len(report.modified)} modified, "
        f"{len(report.missing)} missing, {len(report.untracked)} untracked"
    )
    if report.is_clean:
        # The claim is narrowed when local edits exist, because the unnarrowed
        # version contradicts the banner directly above it — and a report that
        # argues with itself is worse than a terse one. `local_edits` does NOT
        # make the run fail: it is a known, deliberate, permanent state, and a
        # gate that fails every run forever is one that gets switched off.
        if report.local_edits:
            lines.append(
                f"Every vendored file matches the manifest, but "
                f"{len(report.local_edits)} carries a deliberate local edit "
                f"(above) that an update WILL overwrite."
            )
        else:
            lines.append(
                "Every vendored file matches the manifest — an update will not "
                "clobber local work."
            )
    return "\n".join(lines)


def build_manifest(repo_root: Path | str, version: str) -> dict:
    """Hash every vendored file (T053). Used to (re)generate the manifest."""
    root = Path(repo_root)
    files: dict[str, str] = {}
    for vendored_root in VENDORED_ROOTS:
        base = root / vendored_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _is_vendored_candidate(rel, root):
                files[rel] = sha256_of(path)
    # `local_edits` is preserved across rebuilds rather than recomputed: it
    # records a HUMAN judgement ("we changed this on purpose") that no amount of
    # hashing can recover once the edit is baselined.
    existing = {}
    try:
        import json as _json
        existing = _json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    out = {"integration": "speckit", "version": version, "files": files}
    carried = existing.get("local_edits")
    if isinstance(carried, list) and carried:
        out["local_edits"] = sorted(carried)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo-root", default=".")
    p.add_argument("--manifest", default=MANIFEST_PATH)
    p.add_argument("--rebuild", metavar="VERSION",
                   help="Rewrite the manifest, hashing every vendored file")
    args = p.parse_args(argv)

    root = Path(args.repo_root)
    if args.rebuild:
        manifest = build_manifest(root, args.rebuild)
        target = root / args.manifest
        target.parent.mkdir(parents=True, exist_ok=True)
        # `installed_at` is deliberately NOT written: it changes on every
        # rebuild and would make the manifest diff noisy enough that nobody
        # reads it, which is how a drift record stops being read at all.
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.manifest}: {len(manifest['files'])} file(s) hashed")
        return 0

    report = scan(root, args.manifest)
    print(render(report))
    return 0 if report.is_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
