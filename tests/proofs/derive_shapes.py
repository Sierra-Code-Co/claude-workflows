#!/usr/bin/env python3
"""Derive the shapes a failure proof must cover, from the gate itself (FR-008a).

WHY THIS EXISTS, IN ONE SENTENCE: an author writing a proof from recall
reproduces the set the gate already handles, so the proof confirms the
implementation instead of the requirement.

That is not a hypothetical. Both artifacts in this repo shipped with the hole:

  * `raw-caught-to-logger` had eleven fixture shapes and no near-miss for the
    catch-binding unification, so a rule that flagged every identifier inside a
    catch block — `modelId`, `idx`, `toolCallId` — passed the whole proof.
  * the finding-envelope test set covered explicit `claim: null` and never
    covered `claim` ABSENT, so a finding could carry `verdict: confirmed` with
    no claim at all and validate, defeating FR-002 entirely.

Both were found by something other than the author's list. This module makes
that "something other" mechanical.

THE METHOD IS MUTATION, NOT COUNTING.

The obvious implementation — count the rule's constraints, count the fixture's
declared negatives, demand the second be >= the first — is a trap. Both numbers
would come from text the author writes, so a proof could satisfy it by adding a
comment. The count of constraints must come from the gate and the count of
COVERED constraints must come from observed behaviour.

So: drop one constraint from the gate and re-run it against the fixture. If the
reported set does not change, nothing in the fixture distinguishes a gate with
that constraint from one without it. That constraint is unproven, and the gate
could lose it in a refactor with every test still green. No author-supplied list
appears anywhere in the derivation.

The residue this does NOT check, stated plainly rather than left to be
discovered: it proves each constraint is load-bearing, not that each negative
violates exactly one constraint. A single fixture case that violates three
constraints at once would cover all three here while proving none of them
individually. Writing negatives one-violation-at-a-time remains a discipline;
what this removes is the failure to write them at all, which is the one that
actually shipped.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "rules"
FIXTURES_DIR = RULES_DIR / "fixtures"

# Keys that constrain what a rule matches. `stopBy` tunes traversal depth rather
# than the predicate, and dropping it changes reach without removing a claim, so
# it is deliberately absent.
ATOMIC_MATCHERS = ("kind", "pattern", "regex", "field", "nthChild")

# Keys whose values are sub-rules to walk into.
RELATIONAL = ("inside", "has", "follows", "precedes", "not")

# Keys whose values are LISTS of sub-rules.
COMPOSITE = ("all", "any")


class RuleUnparseable(RuntimeError):
    """The mutated rule is not a rule at all — ast-grep refused to load it."""


@dataclass(frozen=True)
class Coverage:
    """What a gate claims, and which of those claims its proof actually tests."""

    artifact: str
    constraints: tuple[str, ...]
    uncovered: tuple[str, ...]
    # Set when the harness itself misbehaved — a mutation that made the gate
    # STRICTER rather than looser means the mutation corrupted the rule, and the
    # coverage verdict derived from it would be measuring the corruption.
    corrupted: tuple[str, ...] = ()
    # Constraints whose removal makes the gate refuse to LOAD. ast-grep requires
    # a root `kind`, so dropping it yields no gate rather than a looser one.
    #
    # These are exempt from the coverage demand, and the reasoning is worth
    # stating because "exempt" is how silent holes start: this validator guards
    # against a constraint being lost QUIETLY, with every test still green. A
    # constraint that takes the whole gate down with it cannot be lost that way —
    # the next run fails to start. So it is a different risk, not an ignored one,
    # and it is printed on every run rather than filtered out of the output.
    unmutable: tuple[str, ...] = ()
    # Constraints with a recorded waiver — no input distinguishes them from their
    # siblings. Reported on every run; see `load_waivers`.
    waived: tuple[str, ...] = ()
    # A waiver for a constraint that is now covered, or that no longer exists in
    # the rule. Both are errors: the first means the exemption outlived its
    # reason, the second means the rule moved and the waiver did not.
    stale_waivers: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        # An empty constraint list is NOT success. "Nothing to cover" and "fully
        # covered" print identically otherwise, which is the same silent-pass
        # shape this whole portfolio exists to close.
        return (
            bool(self.constraints)
            and not self.uncovered
            and not self.corrupted
            and not self.stale_waivers
        )

    def message(self) -> str:
        if not self.constraints:
            return (
                f"{self.artifact}: NO constraints were enumerated. An empty "
                f"enumeration reports full coverage of nothing — treat this as "
                f"a parser failure, not as a passing gate."
            )
        if self.corrupted:
            return (
                f"{self.artifact}: the mutation harness produced a STRICTER gate "
                f"for {', '.join(self.corrupted)}. Dropping a constraint must "
                f"only ever loosen; this means the mutation changed the rule's "
                f"meaning, so no coverage verdict from it can be trusted."
            )
        if self.stale_waivers:
            return (
                f"{self.artifact}: STALE waiver(s) for "
                f"{', '.join(self.stale_waivers)}. Either the constraint is now "
                f"covered by a real near-miss — delete the waiver — or it no "
                f"longer exists in the rule and the waiver was left behind. An "
                f"exemption that outlives its reason is how a gate quietly stops "
                f"proving anything."
            )
        notes = []
        if self.unmutable:
            notes.append(
                f"{len(self.unmutable)} exempt, removing them makes the gate "
                f"refuse to load: {', '.join(self.unmutable)}"
            )
        if self.waived:
            notes.append(
                f"{len(self.waived)} waived as implied by siblings: "
                f"{', '.join(self.waived)}"
            )
        exempt = f" ({'; '.join(notes)})" if notes else ""
        if not self.uncovered:
            return (
                f"{self.artifact}: all {len(self.constraints)} constraint(s) "
                f"covered — each one, when removed, changes what the proof "
                f"observes{exempt}."
            )
        lines = [
            f"{self.artifact}: {len(self.uncovered)} of {len(self.constraints)} "
            f"constraint(s) have NO near-miss negative.",
            "",
            "Removing each of these from the gate changes nothing the proof can "
            "detect, so the gate could lose it in a refactor and stay green:",
        ]
        lines += [f"  - {c}" for c in self.uncovered]
        lines += [
            "",
            "Write one near-miss per line above: a case that violates THAT "
            "constraint and satisfies the rest (FR-008a).",
        ]
        return "\n".join(lines)


# --- structural rules (ast-grep) ---------------------------------------------


def enumerate_rule_constraints(rule: dict) -> list[str]:
    """Every constraint an ast-grep rule file asserts, as dotted paths.

    Includes `files:`/`ignores:` entries. Scope is policy, not plumbing — it
    decides what the rule CLAIMS — and this repo has now been bitten four
    separate times by a scope key that silently matched nothing. A scope glob
    matching nothing looks identical to a clean repo.
    """
    out: list[str] = []
    body = rule.get("rule")
    if isinstance(body, dict):
        _walk(body, "rule", out)
    for key in ("files", "ignores"):
        for i, _ in enumerate(rule.get(key) or []):
            out.append(f"{key}[{i}]")
    return out


def _walk(node: dict, path: str, out: list[str]) -> None:
    for key in ATOMIC_MATCHERS:
        if key in node:
            out.append(f"{path}.{key}")
    for key in RELATIONAL:
        child = node.get(key)
        if isinstance(child, dict):
            _walk(child, f"{path}.{key}", out)
    for key in COMPOSITE:
        seq = node.get(key)
        if isinstance(seq, list):
            for i, item in enumerate(seq):
                if isinstance(item, dict):
                    _walk(item, f"{path}.{key}[{i}]", out)


def drop_rule_constraint(rule: dict, constraint: str) -> dict:
    """Return a copy of `rule` with exactly one constraint RELAXED.

    Deletion is the obvious relaxation and it is wrong for two keys, in a way
    that failed dangerously rather than loudly. `has: {field: function, regex:
    '^console\\.'}` with the regex DELETED becomes `has: {field: function}`,
    which ast-grep refuses to load — it cannot derive a kind set from a field
    name alone. The mutant is unparseable, so the constraint was classified
    "exempt, cannot be lost silently" and dropped from the coverage demand.

    That inverted the result on the two most load-bearing constraints in the
    rule: the console-callee regex and the `$ERR` unification, the exact pair
    that near-misses N2, N3 and N6 exist to prove. A harness limitation was
    reporting itself as a property of the gate. Caught by reading which
    constraints landed in each bucket instead of trusting the green exit.

    So those two are WEAKENED in place instead:
      * a regex becomes `.` — matches any non-empty text, strictly looser;
      * a bare metavariable pattern is RENAMED to a fresh one, which severs the
        unification while leaving "matches any node" intact.
    """
    out = copy.deepcopy(rule)
    if constraint.startswith(("files[", "ignores[")):
        key, idx = constraint.rstrip("]").split("[")
        out[key] = [v for i, v in enumerate(out[key]) if i != int(idx)]
        if not out[key]:
            # ast-grep treats an empty list differently from an absent key, and
            # the difference is not a relaxation. Remove the key outright.
            del out[key]
        return out

    parts = constraint.split(".")
    node = out
    for part in parts[:-1]:
        if part.endswith("]"):
            name, idx = part.rstrip("]").split("[")
            node = node[name][int(idx)]
        else:
            node = node[part]

    leaf = parts[-1]
    value = node[leaf]
    if leaf == "regex":
        node[leaf] = "."
    elif leaf == "pattern" and isinstance(value, str) and _is_bare_metavariable(value):
        node[leaf] = "$__SHAPE_PROBE_UNUSED"
    else:
        del node[leaf]
    return out


def _is_bare_metavariable(pattern: str) -> bool:
    text = pattern.strip()
    return text.startswith("$") and text[1:].replace("_", "").isalnum()


def scan(rule: dict, root: Path) -> set[tuple[str, int]]:
    """Reported (file, line) pairs for `rule` over the tree at `root`.

    The rule is written to a temp file next to nothing in particular, which is
    safe here only because every glob in these rules is either anchored with a
    leading `**/` or is the `fixtures/**` exclusion — and the caller is required
    to have copied the fixture tree OUT from under `rules/fixtures/` first.
    ast-grep resolves `files:`/`ignores:` relative to the RULE FILE'S directory,
    so scanning the fixture in place would silently report nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rule.yml"
        path.write_text(yaml.safe_dump(rule, sort_keys=False))
        try:
            proc = subprocess.run(
                ["ast-grep", "scan", "--rule", str(path), "--json", str(root)],
                capture_output=True, text=True, check=False, timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            # A mutant is a rule nobody wrote by hand, so pathological
            # backtracking is a live possibility. Without this the whole proof
            # suite hangs with no diagnostic — and a hung gate is the one
            # failure mode worse than a silent one, because it stops the run
            # that would have reported it.
            raise RuntimeError(
                f"ast-grep did not finish within 120s on a mutated rule; "
                f"the mutation is likely pathological: {exc}"
            ) from exc
    if proc.returncode not in (0, 1):
        # Discriminated on stderr text, not on the exit code alone: ast-grep
        # uses 8 for several config-level problems, and conflating "this mutant
        # is not a rule" with "the tool is broken" would let a genuinely broken
        # environment read as a batch of exempt constraints.
        if "not a valid ast-grep rule" in proc.stderr or "Cannot parse rule" in proc.stderr:
            raise RuleUnparseable(proc.stderr.strip())
        raise RuntimeError(f"ast-grep failed ({proc.returncode}): {proc.stderr}")
    out = proc.stdout.strip()
    matches = json.loads(out) if out else []

    # Containment, checked rather than assumed. A rule file controls `files:`
    # globs, and a match reported outside the scan root would make a bare
    # `relative_to` raise ValueError — an unhandled crash inside the harness
    # that is supposed to be reporting on gates. Named explicitly instead,
    # because a path escaping the tree is a finding about the RULE, not a glitch.
    resolved_root = root.resolve()
    reported: set[tuple[str, int]] = set()
    for m in matches:
        path = Path(m["file"]).resolve()
        try:
            rel = path.relative_to(resolved_root)
        except ValueError:
            raise RuntimeError(
                f"ast-grep reported a match outside the scan root: {path} is not "
                f"under {resolved_root}. A rule's globs should not be able to "
                f"reach out of the tree being scanned."
            ) from None
        start = m["range"]["start"]
        # COLUMN INCLUDED, not just the line. Collapsing to (file, line) means a
        # mutation that adds a SECOND match on an already-matched line leaves the
        # reported set unchanged — so the constraint reads as uncovered when the
        # fixture does exercise it. A false "uncovered" sends the author to write
        # a near-miss that already exists; worse, the same collapse hides a real
        # widening, which is the direction this validator must never miss.
        reported.add((rel.as_posix(), start["line"] + 1, start["column"]))
    return reported


WAIVER_FILE = "shape-waivers.yml"


def load_waivers(fixture_dir: Path) -> dict[str, str]:
    """Constraints an author has recorded as having no constructible near-miss.

    A waiver does NOT reintroduce the recall problem, and the distinction is the
    whole reason this is allowed to exist: the author cannot waive a constraint
    the validator has not already enumerated FROM THE GATE. Adding a constraint
    to a rule still raises the bar automatically, and the new one arrives
    unwaived and unproven. What a waiver buys is the ability to say "no input can
    distinguish this constraint from its siblings" — which was true of four of the
    first six findings, and is not something a mutation over one fixture can
    decide for itself.

    Two properties keep it from becoming a rubber stamp:
      * a waiver naming a COVERED constraint is an error, not a no-op, so stale
        waivers surface instead of accumulating as folklore;
      * every waiver is printed on every run, so the exemption is visible in the
        same output as the verdict rather than buried in a file nobody opens.
    """
    path = fixture_dir / WAIVER_FILE
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        # `or {}` only rescues None. A file that parses to a list or a bare
        # scalar reaches .get() and dies with AttributeError, which reads as a
        # harness crash rather than the malformed-config error it is.
        raise ValueError(
            f"{path}: expected a mapping at the top level, got "
            f"{type(data).__name__}. The file should read `waivers:` followed "
            f"by constraint -> reason entries."
        )
    waivers = data.get("waivers") or {}
    if not isinstance(waivers, dict):
        raise ValueError(f"{path}: `waivers` must be a mapping of constraint -> reason")
    bad = [k for k, v in waivers.items() if not isinstance(v, str) or not v.strip()]
    if bad:
        raise ValueError(
            f"{path}: every waiver needs a non-empty reason naming the sibling "
            f"constraint that implies it. Missing for: {', '.join(sorted(bad))}"
        )
    return waivers


def check_structural_rule(
    rule_path: Path,
    fixture_root: Path,
    waivers: dict[str, str] | None = None,
) -> Coverage:
    """Mutation coverage for an ast-grep rule against its fixture tree."""
    rule = yaml.safe_load(rule_path.read_text())
    constraints = enumerate_rule_constraints(rule)
    baseline = scan(rule, fixture_root)

    uncovered: list[str] = []
    corrupted: list[str] = []
    unmutable: list[str] = []
    for constraint in constraints:
        mutated = drop_rule_constraint(rule, constraint)
        try:
            observed = scan(mutated, fixture_root)
        except RuleUnparseable:
            unmutable.append(constraint)
            continue
        if observed == baseline:
            uncovered.append(constraint)
            continue
        # Direction control, and POLARITY decides which direction is correct.
        # Dropping a body constraint or an EXCLUSION widens the match set;
        # dropping an INCLUDE narrows the file set. Anything else means the
        # mutation changed meaning rather than removing a restriction.
        #
        # A constraint under a `not:` inverts too, for the same reason an
        # include does: it restricts what gets EXCLUDED, so removing it excludes
        # MORE and the rule reports FEWER. Discovered when the shadow-exclusion
        # clause landed and this classifier called a correct rule "corrupted"
        # for ten findings — the harness's own assumption, stated as if it were
        # the rule's fault. An invariant that only holds for positive
        # constraints reads as universal until someone writes a negation.
        #
        # Odd nesting count, not mere presence: a `not` inside a `not` is
        # positive again. No such rule exists today; the arithmetic is written
        # correctly anyway, because the failure mode is a silently wrong verdict.
        widened = baseline <= observed
        narrowed = observed <= baseline
        negations = constraint.count(".not.") + constraint.startswith("not.")
        inverted = constraint.startswith("files[") or negations % 2 == 1
        if inverted:
            if not narrowed:
                corrupted.append(constraint)
        elif not widened:
            corrupted.append(constraint)

    declared = waivers or {}
    covered = set(constraints) - set(uncovered) - set(unmutable) - set(corrupted)
    stale = tuple(sorted(k for k in declared if k in covered))
    unknown = tuple(sorted(k for k in declared if k not in constraints))
    waived = tuple(c for c in uncovered if c in declared)
    uncovered = [c for c in uncovered if c not in declared]

    return Coverage(
        artifact=rule_path.stem,
        constraints=tuple(constraints),
        uncovered=tuple(uncovered),
        corrupted=tuple(corrupted),
        unmutable=tuple(unmutable),
        waived=waived,
        stale_waivers=stale + unknown,
    )


# --- schema invariants --------------------------------------------------------


def enumerate_schema_conditional_fields(schema: dict) -> list[str]:
    """Every field named in an `if` clause, at any depth.

    A JSON Schema `if` whose `properties` name a field succeeds VACUOUSLY when
    that field is absent. So absence is a distinct branch of the conditional, and
    a test set that only ever supplies values cannot tell `if: {properties: X}`
    from `if: {properties: X, required: [X]}` — the exact pair whose difference
    was the omitted-claim bypass.
    """
    found: list[str] = []
    _walk_schema(schema, found)
    seen: set[str] = set()
    return [f for f in found if not (f in seen or seen.add(f))]


def _walk_schema(node, found: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_schema(item, found)
        return
    if not isinstance(node, dict):
        return
    cond = node.get("if")
    if isinstance(cond, dict):
        found.extend(sorted((cond.get("properties") or {}).keys()))
    for value in node.values():
        _walk_schema(value, found)


def check_schema_field_absence(schema: dict, cases: list[dict]) -> Coverage:
    """Every conditional field needs a case that OMITS it, not merely nulls it."""
    fields = enumerate_schema_conditional_fields(schema)
    uncovered = tuple(f for f in fields if all(f in c for c in cases))
    return Coverage(
        artifact=schema.get("title", schema.get("$id", "<schema>")),
        constraints=tuple(fields),
        uncovered=uncovered,
    )


# --- CLI ----------------------------------------------------------------------


def check_all_rules() -> list[Coverage]:
    """Every rule in rules/, against its fixture tree.

    Copies each tree to a temp dir first, for the reason spelled out in `scan`.
    """
    import shutil

    results: list[Coverage] = []
    for rule_path in sorted(RULES_DIR.glob("*.yml")):
        fixture = FIXTURES_DIR / rule_path.stem
        if not fixture.is_dir():
            results.append(Coverage(
                artifact=rule_path.stem, constraints=(), uncovered=(),
            ))
            continue
        if fixture.is_symlink():
            # `is_dir()` follows symlinks and copytree(symlinks=True) preserves
            # links inside the tree but still resolves the ROOT it is handed, so
            # a symlinked fixture directory would pull an arbitrary tree into the
            # scan. Fixtures arrive by PR like any other file.
            results.append(Coverage(
                artifact=f"{rule_path.stem} (fixture path is a symlink; refused)",
                constraints=(), uncovered=(),
            ))
            continue
        waivers = load_waivers(fixture)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            # symlinks=True: copy links AS links rather than dereferencing them.
            # The default follows them, so a fixture carrying a symlink to an
            # absolute path outside the repo would have its target copied into
            # the scan tree and its contents quoted back in findings. Fixtures
            # arrive via PR like any other file.
            shutil.copytree(fixture, root, symlinks=True)
            results.append(check_structural_rule(rule_path, root, waivers))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    if not shutil_which("ast-grep"):
        # Fail, never skip. A shape validator that silently does not run reports
        # no uncovered constraints, which reads exactly like full coverage.
        print("FAIL: ast-grep is not installed, so no gate's shape coverage was "
              "derived at all.", file=sys.stderr)
        return 1

    results = check_all_rules()
    if not results:
        print(f"FAIL: no rules found in {RULES_DIR}; an empty sweep is not a "
              f"passing sweep.", file=sys.stderr)
        return 1

    bad = [r for r in results if not r.ok]
    for r in results:
        status = "ok  " if r.ok else "FAIL"
        # Exemptions are printed on EVERY run, including green ones. A waiver
        # visible only in a file nobody opens is how an exemption becomes
        # folklore; the count belongs next to the verdict it qualifies.
        # Every category is subtracted, including `uncovered`. An earlier
        # version omitted it and reported "7/13 proven" on a run whose whole
        # point was that one of those 7 was not proven at all — a status line
        # contradicting the failure printed directly beneath it.
        accounted = len(r.waived) + len(r.unmutable) + len(r.uncovered) + len(r.corrupted)
        proven = len(r.constraints) - accounted
        notes = []
        if r.uncovered:
            notes.append(f"{len(r.uncovered)} UNCOVERED")
        if r.waived:
            notes.append(f"{len(r.waived)} waived")
        if r.unmutable:
            notes.append(f"{len(r.unmutable)} unmutable")
        extra = f" [{', '.join(notes)} — see {WAIVER_FILE}]" if notes else ""
        print(f"  {status} {r.artifact}: {proven}/{len(r.constraints)} "
              f"constraint(s) proven by near-miss{extra}")
    if bad:
        print()
        for r in bad:
            print(r.message())
            print()
        return 1
    return 0


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
