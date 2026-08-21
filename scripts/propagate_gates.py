"""Propagate `rules/` and a gate registry downstream (T021b, T064, Principle VII).

`propagate-skill.sh` copies ONE `SKILL.md` per skill and knows nothing about
`rules/` directories or `gates.yml`. T021b and T064 both name it as the
mechanism; it cannot do this. So this exists.

THE RULE THIS TOOL ENFORCES BY CONSTRUCTION: a gate enters `blocking` only at a
MEASURED baseline of zero. Not "usually", not "unless you pass --force" — the
tier is DERIVED from a scan of the target repo, and there is no flag to override
it. FR-014's advisory tier exists to absorb noise, and this repo's own history
is the argument: markdownlint entered with a 2541-finding baseline and became a
gate nobody could ever make green, which is indistinguishable from having no
gate at all.

Measured 2026-08-16 on the fleet, which is why the derivation is not decorative:

    mtg-cube-ai   0 findings  -> blocking
    companion-ai  4 findings  -> advisory, and 4 issues to fix first

Registering the rule as blocking in companion-ai would have shipped a red gate
on day one, in a repo that never asked for it.

DRY RUN BY DEFAULT. This writes into OTHER PEOPLE'S REPOSITORIES; the default
has to be the one that cannot surprise anyone. `--apply` opts in, and even then
an existing `gates.yml` is never silently overwritten.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HOME_PROJECTS = Path.home() / "dev" / "projects"
TRUNK = Path(__file__).resolve().parents[1]

#: Never propagate into these: the trunk itself, the template it is copied from,
#: and any worktree (which shares its parent's .git and would double-apply).
_SKIP_NAMES = {"claude-workflows", "claude-speckit-template"}
_SKIP_PARTS = {"worktrees", "node_modules", "_archive"}


@dataclass
class Target:
    path: Path
    baseline: int | None = None      # None = not measured (never treat as 0)
    in_scope_files: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def tier(self) -> str:
        """DERIVED from the baseline. There is deliberately no override flag.

        `None` — unmeasured — yields advisory, never blocking. "We could not
        measure it" must never resolve in favour of the stricter setting; that
        is how a repo gets a red gate it never agreed to.
        """
        return "blocks" if self.baseline == 0 else "advisory"

    @property
    def reason(self) -> str:
        if self.baseline is None:
            return "baseline not measured — advisory until it is"
        if self.baseline == 0:
            return "measured baseline of ZERO, so there is no backlog to grant amnesty to"
        return (
            f"{self.baseline} pre-existing finding(s) — blocking here would ship a "
            f"gate that is red on day one, which is how gates get switched off"
        )


def discover(explicit: list[str] | None = None) -> list[Target]:
    if explicit:
        return [Target(path=(HOME_PROJECTS / n).resolve()) for n in explicit]
    out: list[Target] = []
    for claude_dir in sorted(HOME_PROJECTS.glob("*/.claude")):
        repo = claude_dir.parent
        if repo.name in _SKIP_NAMES or _SKIP_PARTS & set(repo.parts):
            continue
        if not (repo / ".git").exists():
            continue
        if is_worktree(repo):
            # A linked worktree SHARES its parent's repository. Writing here
            # would commit the same files twice through two checkouts, onto
            # whatever feature branch that worktree happens to be on. Detected
            # STRUCTURALLY (git-dir != git-common-dir), not by a name pattern:
            # `companion-ai-wt-milestones` is a top-level sibling directory, so
            # a path-based `worktrees` filter misses it entirely — which the
            # first dry run of this tool duly demonstrated.
            continue
        out.append(Target(path=repo))
    return out


def is_worktree(repo: Path) -> bool:
    try:
        git_dir = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo,
                                 capture_output=True, text=True, check=True).stdout.strip()
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo,
                                capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        # Cannot tell -> treat as a worktree and SKIP. Declining to write is
        # always recoverable; writing into a shared checkout is not.
        return True
    return Path(git_dir).resolve() != Path(common).resolve()


def count_in_scope(repo: Path) -> int:
    """Files a TypeScript server rule could apply to. Zero means 'not for you'."""
    n = 0
    for pattern in ("src/lib/server", "src/routes/api"):
        for p in repo.rglob("*.ts"):
            parts = set(p.parts)
            if parts & {"node_modules", ".svelte-kit", "build", "dist"}:
                continue
            if pattern.replace("/", "|") in "|".join(p.parts):
                n += 1
    return n


#: Proof material THIS TOOL SHIPS. It contains seeded violations by design, so
#: counting it as the target's backlog is a category error.
#:
#: Excluded EXPLICITLY rather than by leaning on the rule's own `ignores:`,
#: because those globs resolve relative to the RULE FILE'S directory. Measuring
#: with the trunk's rule means `fixtures/**` points at the trunk's fixtures, and
#: the copy sitting in the target repo is not excluded at all.
#:
#: That is not hypothetical: the second propagation run reported mtg-cube-ai at
#: 10 and companion-ai at 14, against directly-measured 0 and 4. Every extra
#: finding was this tool's own seeded proof material. Left alone it would have
#: flipped mtg-cube-ai from `blocks` to `advisory` on the next run — a silent
#: DOWNGRADE of a gate, decided by a mis-scoped measurement, in the one function
#: whose entire job is deciding that tier. Fifth scope-key surprise on this rule.
_PROOF_MATERIAL_GLOB = "!rules/fixtures/**"


def measure(repo: Path, rule: Path, timeout: int = 300) -> int | None:
    """Run the rule. None on any failure — NEVER 0, which would read as clean."""
    if shutil.which("ast-grep") is None:
        return None
    try:
        proc = subprocess.run(
            ["ast-grep", "scan", "--rule", str(rule),
             "--globs", _PROOF_MATERIAL_GLOB, "--json"],
            cwd=repo, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode not in (0, 1):
        return None
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return len(data) if isinstance(data, list) else None


def gates_yml_for(target: Target, rule_name: str) -> str:
    return f"""\
# Propagated from claude-workflows (Principle VII: fix upstream, propagate down).
# DO NOT EDIT HERE. Regenerate from a claude-workflows checkout with:
#   python3 scripts/propagate_gates.py --apply
# That script lives in claude-workflows ONLY. The path above resolves to nothing
# in this repo, and that is the point: this file is a copy, not a source. The
# fields below are declarative — CI does not read them, so treat a change here
# as documentation until a consumer exists.
#
# TIER IS DERIVED, NOT CHOSEN. `blocking` below was set from a measured scan of
# THIS repo, not copied from the trunk: {target.reason}.
#
# Re-measure before promoting:
#   ast-grep scan --rule rules/{rule_name}.yml --json | jq length
version: 1

gates:
  - id: structural.{rule_name}
    tier: deterministic
    blocking: {target.tier}
    order: 20
    cost: free
    rule: rules/{rule_name}.yml
    failure_proof: rules/fixtures/{rule_name}/prove.sh
    enabled_since: "2026-08-16"
"""


#: The trunk's own failure proof. The propagated copy is DERIVED from this file
#: rather than hand-written beside it.
TRUNK_PROOF = TRUNK / "tests" / "proofs" / "raw_caught_to_logger.sh"

#: The trunk resolves its rule from the repo root; a propagated proof sits at
#: `rules/fixtures/<rule>/prove.sh` and resolves it two levels up. That path
#: block is the ONLY difference between the two, so it is the only thing
#: rewritten.
_TRUNK_RULE_BLOCK = "\n".join(
    [
        'PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        'REPO_ROOT="${REPO_ROOT:-$(cd -- "${PROOF_DIR}/../.." && pwd)}"',
        'RULE="${REPO_ROOT}/rules/raw-caught-to-logger.yml"',
    ]
)


def proof_for(rule_name: str) -> str:
    """The trunk proof, re-pathed for a downstream `rules/fixtures/<rule>/`.

    DERIVED, NOT COPIED, and that is the whole point. The first version of this
    was a hand-written variant of the trunk proof, and it drifted immediately:
    it counted `"ruleId"` occurrences through `grep -c ... || true` with stderr
    discarded, so an ast-grep that failed to run returned 0 and the clean-tree
    check passed on a scanner that never scanned. Review caught it downstream
    (mtg-cube-ai#2120).

    That is the same defect as #2110 one level up — a fix applied to one of
    several copies — so the copies are now one file. A proof that cannot fail is
    not a proof, and two proofs that can drift are one proof and one liability.
    """
    body = TRUNK_PROOF.read_text()
    if _TRUNK_RULE_BLOCK not in body:
        # Never fall back to a hand-written variant: silently shipping a weaker
        # proof is the failure this function exists to prevent.
        raise SystemExit(
            f"ERROR: {TRUNK_PROOF} no longer contains the expected rule-path "
            f"block, so the propagated proof cannot be derived from it. Fix the "
            f"block or update _TRUNK_RULE_BLOCK — do not hand-write a copy."
        )
    replacement = (
        'PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
        'RULE="${PROOF_DIR}/../../' + rule_name + '.yml"'
    )
    out = body.replace(_TRUNK_RULE_BLOCK, replacement, 1)
    # The sign-off names the gate. Left unrewritten, a propagated proof for
    # another rule prints someone else's rule id on success — a small lie, but
    # this is the file an operator reads to decide whether a gate is proven.
    out = out.replace("raw-caught-to-logger goes red", f"{rule_name} goes red", 1)
    return out.replace(
        "# Failure proof for gate `structural.raw-caught-to-logger` (FR-007).",
        f"# Failure proof for gate `structural.{rule_name}` (FR-007), propagated\n"
        f"# from claude-workflows. DERIVED from tests/proofs/raw_caught_to_logger.sh\n"
        f"# there — edit it upstream, not here, or the two drift and a fix lands on\n"
        f"# only one of them (which is mtg-cube-ai#2110 in one sentence).",
        1,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Default is a dry run, because this "
                         "writes into other repositories.")
    ap.add_argument("--only", nargs="*", help="limit to these project names")
    ap.add_argument("--rule", default="raw-caught-to-logger")
    args = ap.parse_args(argv)

    rule_src = TRUNK / "rules" / f"{args.rule}.yml"
    if not rule_src.is_file():
        print(f"ERROR: no such rule: {rule_src}", file=sys.stderr)
        return 2

    targets = discover(args.only)
    applicable, skipped = [], []
    for t in targets:
        t.in_scope_files = count_in_scope(t.path)
        if t.in_scope_files == 0:
            skipped.append(t)
            continue
        t.baseline = measure(t.path, rule_src)
        applicable.append(t)

    mode = "APPLY" if args.apply else "DRY RUN (pass --apply to write)"
    print(f"propagate_gates: rule '{args.rule}', {mode}\n")

    # Named, not counted: "12 repos skipped" hides which, and a repo skipped by
    # mistake is indistinguishable from one skipped correctly.
    if skipped:
        print(f"NOT APPLICABLE ({len(skipped)}) — no files the rule could match:")
        for t in skipped:
            print(f"  - {t.name}")
        print()

    for t in applicable:
        base = "unmeasured" if t.baseline is None else str(t.baseline)
        print(f"{t.name}: {t.in_scope_files} in-scope file(s), baseline={base} "
              f"-> {t.tier}")
        print(f"    {t.reason}")
        if not args.apply:
            continue

        dest_rules = t.path / "rules"
        dest_rules.mkdir(exist_ok=True)
        shutil.copy2(rule_src, dest_rules / rule_src.name)
        fixtures = TRUNK / "rules" / "fixtures" / args.rule
        if fixtures.is_dir():
            shutil.copytree(fixtures, dest_rules / "fixtures" / args.rule,
                            dirs_exist_ok=True)
            # FR-007: the declared failure_proof must RESOLVE, and SC-004 runs
            # it. The first draft of this tool pointed at a README.md that does
            # not exist — every propagated gates.yml would have been REFUSED by
            # the registry loader, shipping a portfolio that cannot load. Caught
            # by checking the path before writing rather than after.
            proof = dest_rules / "fixtures" / args.rule / "prove.sh"
            proof.write_text(proof_for(args.rule))
            proof.chmod(0o755)

        gates = t.path / "gates.yml"
        if gates.exists():
            # NEVER silently overwrite: a downstream repo may have promoted a
            # gate, added its own, or recorded acceptance we would destroy.
            print(f"    gates.yml EXISTS — not overwritten. Proposed tier for "
                  f"structural.{args.rule}: {t.tier}. Merge by hand.")
        else:
            gates.write_text(gates_yml_for(t, args.rule))
            print(f"    wrote {gates.relative_to(t.path)} and rules/{rule_src.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
