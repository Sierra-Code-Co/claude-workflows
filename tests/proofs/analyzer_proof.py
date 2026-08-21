#!/usr/bin/env python3
"""Shared driver for the four static-analyzer failure proofs (T035, FR-007).

WHAT THIS PROVES, AND WHAT IT DELIBERATELY DOES NOT.

It drives the ANALYZER CLASS, not the binary. Shelling out to `gitleaks detect`
and asserting a non-zero exit proves gitleaks works — which was never in doubt —
while saying nothing about whether our wrapper's glob selection, output parsing,
or severity mapping turn that exit code into a Finding anyone sees. Every
silent-degradation incident in this fleet lived in the wrapper: a scope glob that
matched nothing, a parser that swallowed an error shape, a skip that read as a
pass. So the assertion is on `AnalyzerResult.findings`, the thing the aggregator
consumes.

Three assertions per analyzer, and the third is the one usually missing:

  1. a clean file yields no findings — otherwise "it went red" is satisfied by a
     gate that is red about everything;
  2. a seeded violation yields at least one finding that NAMES the seeded file;
  3. restoring the file goes green again.

A MISSING BINARY IS A FAILURE, NOT A SKIP. `StaticAnalyzer.run()` returns
`skipped=True` with zero findings when its binary is absent, which is
byte-identical to a clean result at the call site. That is the T005i defect
exactly — an assertion that does not run reads as an assertion that passed — so
`skipped` is checked explicitly and fails the proof.

SECRETS ARE CONSTRUCTED AT RUNTIME. The gitleaks seed is assembled from
fragments rather than written as a literal, because this repo's own CI runs
gitleaks over itself: a committed test secret would either fail our own scan or,
worse, teach us to add an allowlist entry that then hides real ones.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from review_plan_v2.analyzers.actionlint import ActionlintAnalyzer  # noqa: E402
from review_plan_v2.analyzers.gitleaks import GitleaksAnalyzer  # noqa: E402
from review_plan_v2.analyzers.markdownlint import MarkdownlintAnalyzer  # noqa: E402
from review_plan_v2.analyzers.ruff import RuffAnalyzer  # noqa: E402
from review_plan_v2.analyzers.shellcheck import ShellcheckAnalyzer  # noqa: E402
from review_plan_v2.types import FileChange  # noqa: E402

# Assembled at runtime; see the module docstring.
#
# THE FIRST SEED I CHOSE DID NOT WORK, AND FAILED SILENTLY IN THE INTERESTING
# DIRECTION. `AKIAIOSFODNN7EXAMPLE` — the AWS documentation example key, the
# obvious thing to reach for — is ALLOWLISTED by gitleaks 8.30.1 as a known
# documentation value, so it reports "no leaks found". Anyone sanity-checking
# secret detection with it watches a gate never fire and concludes it works.
# That is this portfolio's defect class exactly, met while building the proof
# that exists to catch it.
#
# A synthetic GitHub PAT is used instead: detected by `github-pat`, and the most
# relevant leak shape for a repo full of workflow automation. Verified against
# the installed gitleaks, not assumed from the rule list.
_PAT_SEED = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

SEEDS: dict[str, dict] = {
    "gitleaks": {
        "analyzer": GitleaksAnalyzer,
        "filename": "config.py",
        "clean": 'TOKEN = os.environ["GITHUB_TOKEN"]\n',
        "dirty": f'TOKEN = "{_PAT_SEED}"\n',
        "seeded": "a hardcoded GitHub personal access token",
    },
    "markdownlint": {
        "analyzer": MarkdownlintAnalyzer,
        "filename": "doc.md",
        "clean": "# Title\n\nBody text.\n",
        # MD018: no space after the hash on an ATX heading.
        "dirty": "#Title\n\nBody text.\n",
        "seeded": "an ATX heading with no space after the hash (MD018)",
    },
    "actionlint": {
        "analyzer": ActionlintAnalyzer,
        "filename": ".github/workflows/proof.yml",
        "clean": (
            "name: proof\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: echo hello\n"
        ),
        # An undefined context property — the class of mistake that only shows
        # up when the workflow actually runs, which is why actionlint is in the
        # portfolio at all.
        "dirty": (
            "name: proof\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: echo ${{ github.no_such_property }}\n"
        ),
        "seeded": "an undefined github context property",
    },
    "ruff": {
        "analyzer": RuffAnalyzer,
        "filename": "mod.py",
        "clean": "import os\n\n\ndef where() -> str:\n    return os.getcwd()\n",
        # F401, the rule that found three live unused imports in scripts/ the
        # day this analyzer was written. Chosen over a style rule on purpose:
        # the proof should exercise the pyflakes family this gate is actually
        # here for, not the cosmetic tail.
        "dirty": "import os\nimport json\n\n\ndef where() -> str:\n    return os.getcwd()\n",
        "seeded": "an unused import (F401)",
    },
    "shellcheck": {
        "analyzer": ShellcheckAnalyzer,
        "filename": "script.sh",
        "clean": '#!/usr/bin/env bash\ndir="$1"\nrm -rf "${dir:?}"\n',
        # SC2086: unquoted expansion. Chosen because the failure it causes —
        # word splitting on a path — is the one that turns `rm -rf` into an
        # incident rather than an error.
        "dirty": '#!/usr/bin/env bash\ndir="$1"\nrm -rf $dir\n',
        "seeded": "an unquoted variable expansion in rm -rf (SC2086)",
    },
}


def _change(path: str) -> FileChange:
    return FileChange(
        path=path,
        is_binary=False,
        is_renamed_from=None,
        added_lines=((1, 50),),
        diff_text="",
        language=None,
    )


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def prove(name: str) -> int:
    spec = SEEDS[name]
    analyzer = spec["analyzer"]()

    if shutil.which(analyzer.binary) is None:
        return _fail(
            f"{analyzer.binary} is not installed, so gate '{name}' was not proven "
            f"at all. This is a hard failure and not a skip: an analyzer that "
            f"does not run reports zero findings, which is byte-identical to a "
            f"clean result at every call site downstream."
        )

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        target = workdir / spec["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        change = _change(spec["filename"])

        # Scope check first. If the seeded path does not match the analyzer's
        # globs it reports zero findings for a reason that has nothing to do
        # with the seed, and the proof would blame the gate for a fixture bug.
        # This repo has now been bitten four times by a scope key that silently
        # matched nothing.
        if not analyzer.applicable_files([change]):
            return _fail(
                f"{name}: the seeded path {spec['filename']!r} matches none of "
                f"{analyzer.applicable_globs}, so this proof would exercise "
                f"nothing. Fix the fixture path, not the gate."
            )

        # Every run goes through here, and the skipped check lives HERE rather
        # than at each call site.
        #
        # It was written three times and I got it right twice: the restore phase
        # checked only `findings`, so a skipped analyzer — zero findings by
        # construction — printed `ok` for a gate that never ran. That is the
        # T005i defect, inside the file whose docstring declares in capitals that
        # skipped is a hard failure. Anything each call site has to remember,
        # some call site will forget; the fix belongs at the choke point, not on
        # the branch that happened to be caught.
        def run(phase: str) -> tuple[list, str | None]:
            res = analyzer.run([change], workdir=str(workdir))
            if res.skipped:
                return [], (
                    f"{name}: analyzer reported SKIPPED during the {phase} phase "
                    f"({res.skip_reason}). Zero findings from a skipped run is "
                    f"byte-identical to a clean result, so this proof would "
                    f"otherwise credit a gate that never executed."
                )
            return res.findings, None

        # 1. clean must be green
        target.write_text(spec["clean"])
        findings, err = run("clean")
        if err:
            return _fail(err)
        if findings:
            return _fail(
                f"{name}: the CLEAN file produced {len(findings)} finding(s), "
                f"so a red result proves nothing about the seed: "
                f"{[f.message for f in findings][:3]}"
            )

        # 2. seeded violation must go red, and must say where
        target.write_text(spec["dirty"])
        findings, err = run("seeded")
        if err:
            return _fail(err)
        if not findings:
            return _fail(
                f"{name}: seeded {spec['seeded']} was NOT detected. The gate "
                f"returned zero findings, which is the state this proof exists "
                f"to make impossible."
            )
        if not any(spec["filename"] in (f.file or "") for f in findings):
            return _fail(
                f"{name}: findings were produced but none names the seeded file "
                f"{spec['filename']!r}: {[(f.file, f.message) for f in findings][:3]}. "
                f"A finding with no location is not actionable."
            )

        # 3. restore must go green again
        target.write_text(spec["clean"])
        findings, err = run("restore")
        if err:
            return _fail(err)
        if findings:
            return _fail(
                f"{name}: the gate stayed red after the violation was removed: "
                f"{[f.message for f in findings][:3]}"
            )

    print(f"ok: {name} goes red on {spec['seeded']} and green on restore")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SEEDS:
        print(f"usage: {sys.argv[0]} <{'|'.join(SEEDS)}>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(prove(sys.argv[1]))
