"""The toolchain a gate depends on must be declared where the run can see it.

Deliberately written with NO `sys.path.insert` — 16 of the 17 test files in this
suite hand-rolled that line because there was nowhere to declare it. This file
doubles as the standing proof that `[tool.pytest.ini_options] pythonpath` in
pyproject.toml resolves the package, so new tests do not have to repeat the hack.
Remove `pythonpath` and this file fails at collection, not at assertion.

The ast-grep assertion is not ceremony. Writing it is what caught the fact that
the check_deps edit claimed in the T001 commit message had silently not applied.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from review_plan_v2 import check_deps

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ast_grep_is_a_declared_dependency():
    """The structural enumerator must appear in the dependency check.

    Otherwise a machine without ast-grep runs the whole portfolio, skips every
    structural gate, and reports a clean run — the Principle I failure mode.
    """
    assert "ast-grep" in check_deps.RECOMMENDED


def test_ast_grep_is_not_required():
    """RECOMMENDED, not REQUIRED.

    A missing enumerator must degrade to a reported gap (T018), not abort the
    run. If someone promotes it to REQUIRED, the degradation path stops being
    exercised and the 'no deterministic coverage' branch rots untested.
    """
    assert "ast-grep" not in check_deps.REQUIRED


def test_ast_grep_pin_matches_between_ci_and_the_image():
    """The version is written in two files. A comment saying "keep these in
    sync" is not a mechanism.

    This is the shellcheck drift in advance: that binary was 0.9.0 in the image
    and 0.11.0 on the host for a day, and every check reported ok because
    nothing compared the two numbers. Here the numbers decide whether a
    completeness result from CI and one from the container are comparable at
    all, so a skew silently invalidates cross-environment comparison.

    Both inputs are shipped into the image on purpose. The first container run
    after this test was written failed right here with FileNotFoundError —
    a test that could only ever pass on a dev laptop, which is precisely the
    defect `test_contract_file_is_valid_json_schema` had hours earlier. Note
    what it is NOT fixed with: a skip when the files are absent. A drift check
    that silently does not run reports clean.
    """
    docker_path = REPO_ROOT / "Dockerfile"
    workflow_path = REPO_ROOT / ".github" / "workflows" / "tests.yml"
    for p in (docker_path, workflow_path):
        assert p.is_file(), (
            f"{p} is not present, so the pin comparison did not happen. If this "
            f"fires inside the container, .dockerignore or the Dockerfile's COPY "
            f"lines stopped shipping it — fix that, do not skip this test."
        )

    dockerfile = docker_path.read_text()
    workflow = workflow_path.read_text()

    docker_pin = re.search(r"^ARG AST_GREP_VERSION=(\S+)", dockerfile, re.M)
    ci_pin = re.search(r"^\s*AST_GREP_VERSION:\s*(\S+)", workflow, re.M)

    assert docker_pin, "Dockerfile no longer declares ARG AST_GREP_VERSION"
    assert ci_pin, "tests.yml no longer declares AST_GREP_VERSION"
    assert docker_pin.group(1) == ci_pin.group(1), (
        f"ast-grep pin drift: Dockerfile={docker_pin.group(1)}, "
        f"CI={ci_pin.group(1)}"
    )

    # T005d. Pinning the VERSION in both places while pinning the DIGEST in only
    # one leaves the two installs free to diverge on a re-tagged release —
    # exactly the hole digests close, reopened one file over.
    docker_sha = re.search(r"^ARG AST_GREP_SHA256_AMD64=(\S+)", dockerfile, re.M)
    ci_sha = re.search(r"^\s*AST_GREP_SHA256:\s*(\S+)", workflow, re.M)
    assert docker_sha, "Dockerfile no longer declares ARG AST_GREP_SHA256_AMD64"
    assert ci_sha, "tests.yml no longer declares AST_GREP_SHA256"
    assert docker_sha.group(1) == ci_sha.group(1), (
        f"ast-grep DIGEST drift: Dockerfile={docker_sha.group(1)}, "
        f"CI={ci_sha.group(1)} — same version, different bytes"
    )


def test_every_release_download_is_digest_verified():
    """Every `curl` of a release artifact must be verified before it is used.

    DERIVED from the Dockerfile's own structure rather than a remembered list
    (FR-008a): count the downloads, count the verifications, require one each.
    A block that pins five artifacts and verifies four produces a build log
    identical to one that verifies all five — the unverified one simply
    installs. Counting is the only way to see the gap.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    downloads = re.findall(r"curl -fsSL -o (\S+)\s", dockerfile)
    verified = set(re.findall(r'verify "\$\w+" (\S+);', dockerfile))

    assert downloads, "no release downloads found — this regex has gone stale"
    missing = [d for d in downloads if d not in verified]
    assert not missing, (
        f"downloaded but never digest-verified: {missing}. Every release "
        f"artifact must pass `verify`."
    )


def test_verification_precedes_unpacking():
    """ORDER, not just presence — the half the counting test cannot see.

    Reported by review: the test above asserts only that each filename appears
    somewhere in a `verify` call, while its failure message claimed `BEFORE`. A
    Dockerfile that unpacked first and verified afterwards satisfied it
    completely, and that Dockerfile is exploitable: `tar -x` has already written
    to the filesystem by the time the check objects. The message was writing a
    cheque the assertion did not cash.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    # Anything that reads the bytes: unpack, move into place, or execute.
    consumers = ("tar -xJf", "tar -xzf", "tar -xf", "unzip", "zipfile.ZipFile", "mv ")

    checked = 0
    for artifact in re.findall(r"curl -fsSL -o (\S+)\s", dockerfile):
        verified_at = dockerfile.find('verify "$', dockerfile.find(f"-o {artifact}"))
        verified_at = dockerfile.find(artifact, verified_at)
        assert verified_at > 0, f"{artifact} is downloaded but never verified"

        # Walk THIS artifact's own occurrences and look BACKWARDS a short way
        # for a consuming verb. An earlier draft scanned forward 200 chars from
        # each consumer instead, which paired `mv /tmp/yq` with the gitleaks
        # artifact further down the file and failed a correct Dockerfile — the
        # window has to be anchored on the artifact, not on the verb.
        for m in re.finditer(re.escape(artifact), dockerfile):
            prefix = dockerfile[max(0, m.start() - 24):m.start()]
            if not any(c in prefix for c in consumers):
                continue
            assert verified_at < m.start(), (
                f"{artifact} is consumed at offset {m.start()} BEFORE its "
                f"verify at {verified_at} — the bytes are already on disk by "
                f"the time the digest is checked"
            )
            checked += 1

    assert checked >= 5, (
        f"only {checked} consuming uses were examined across 5 artifacts; the "
        f"consumer list has gone stale, so this test is passing by matching "
        f"nothing — the scope-config trap, in a test this time"
    )


def test_the_base_images_are_digest_pinned():
    """A mutable tag on a FROM line is the same drift as an unpinned tarball,
    and the easiest to overlook because it does not look like a download.

    Flags are skipped rather than captured: `FROM --platform=$BUILDPLATFORM img`
    would otherwise yield `--platform=$BUILDPLATFORM`, which contains no
    `@sha256:` and fails a perfectly well-pinned line. Reported by review — a
    false failure, so it fails safe, but a test that breaks on valid input is a
    test somebody deletes.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    froms = []
    for line in re.findall(r"^FROM\s+(.+)$", dockerfile, re.M):
        tokens = [t for t in line.split() if not t.startswith("--")]
        assert tokens, f"FROM line names no image: {line!r}"
        froms.append(tokens[0])

    assert froms, "no FROM lines found — this regex has gone stale"
    unpinned = [f for f in froms if "@sha256:" not in f]
    assert not unpinned, f"base image(s) on a mutable tag: {unpinned}"


def test_the_build_runs_the_test_suite():
    """T005f. `tests/` shipping into the image proves nothing if the build never
    runs them; container parity was a habit, not a gate, until this line."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert re.search(r"^RUN python -m pytest tests/", dockerfile, re.M), (
        "the Dockerfile no longer runs the suite at build time, so a "
        "container-only failure can ship again"
    )


def test_every_registered_analyzer_binary_is_declared():
    """Each shipped analyzer's binary appears in REQUIRED or RECOMMENDED.

    An analyzer whose binary nothing checks for skips silently on a machine that
    lacks it, and `skipped` is not `clean`.
    """
    from review_plan_v2.analyzers import actionlint, gitleaks, markdownlint, shellcheck

    declared = set(check_deps.REQUIRED) | set(check_deps.RECOMMENDED)
    for module in (actionlint, gitleaks, markdownlint, shellcheck):
        analyzers = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and getattr(obj, "binary", "")
        ]
        assert analyzers, f"no analyzer class with a binary found in {module.__name__}"
        for cls in analyzers:
            assert cls.binary in declared, (
                f"{cls.__name__}.binary={cls.binary!r} is not in REQUIRED or "
                f"RECOMMENDED, so a machine without it skips silently"
            )


def test_gitleaks_pin_matches_between_ci_and_the_image():
    """Same mechanism as the ast-grep pin, for the same reason.

    gitleaks became a hard dependency of the pytest job on 2026-08-15 (T005i).
    Two files now name its version, and a comment asking for them to agree is
    not a mechanism — shellcheck already drifted 0.9.0-vs-0.11.0 that way while
    every check reported ok.

    This one carries more weight than the ast-grep pin: gitleaks decides whether
    a secret-bearing diff is caught before the reviewers run, and the secret
    rules change between releases. A CI runner on an older gitleaks would pass
    the suite while detecting less than the image does.
    """
    docker_path = REPO_ROOT / "Dockerfile"
    workflow_path = REPO_ROOT / ".github" / "workflows" / "tests.yml"
    for p in (docker_path, workflow_path):
        assert p.is_file(), (
            f"{p} is not present, so the pin comparison did not happen. If this "
            f"fires inside the container, .dockerignore or the Dockerfile's COPY "
            f"lines stopped shipping it — fix that, do not skip this test."
        )

    docker_pin = re.search(r"^ARG GITLEAKS_VERSION=(\S+)", docker_path.read_text(), re.M)
    ci_pin = re.search(r"^\s*GITLEAKS_VERSION:\s*(\S+)", workflow_path.read_text(), re.M)

    assert docker_pin, "Dockerfile no longer declares ARG GITLEAKS_VERSION"
    assert ci_pin, (
        "tests.yml no longer declares GITLEAKS_VERSION — if the install step was "
        "removed, test_static_analyzers.py now HARD FAILS in CI rather than "
        "skipping, which is the point (T005i)."
    )
    assert docker_pin.group(1) == ci_pin.group(1), (
        f"gitleaks pin drift: Dockerfile={docker_pin.group(1)}, CI={ci_pin.group(1)}"
    )


def test_ci_installs_gitleaks_for_the_pytest_job():
    """The install must live in the SAME job as the suite.

    The repo already had a `gitleaks` job scanning for committed secrets, and
    its presence is exactly what made this defect invisible: two green checks
    named gitleaks, neither of them putting the binary on the runner that runs
    the tests. Jobs do not share a filesystem, so this asserts co-location, not
    mere mention.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    pytest_job = workflow.split("jobs:", 1)[1].split("\n  pytest:", 1)[1]
    # Stop at the next top-level job key, if any.
    next_job = re.search(r"\n  [a-zA-Z0-9_-]+:\n", pytest_job)
    if next_job:
        pytest_job = pytest_job[: next_job.start()]
    assert "GITLEAKS_VERSION" in pytest_job, (
        "the pytest job does not install gitleaks, so "
        "tests/integration/test_static_analyzers.py will hard-fail in CI. That "
        "is better than the silent skip it replaced, but the fix is to restore "
        "the install step (T005i)."
    )
    assert "python -m pytest" in pytest_job, (
        "the suite no longer runs in the job this test inspects; update the parser"
    )


# --- every analyzer the proofs exercise must be ON the pytest runner ----------
#
# markdownlint and actionlint were pinned in the Dockerfile, listed in the
# portfolio, wired into the orchestrator — and never installed on the CI runner.
# `StaticAnalyzer.run()` returns skipped=True with zero findings when its binary
# is absent, and zero findings from a skip is byte-identical to a clean result,
# so two of the four analyzer gates had simply never run in CI and nothing said
# so. The failure proofs found it on their first CI run.
#
# The generalisation is the same one T005i produced for gitleaks: a green check
# named X does not mean X executed. This pins it for every analyzer at once,
# rather than one test per tool that the next tool will not get.

ANALYZER_PINS = {
    "markdownlint": ("ARG MARKDOWNLINT_CLI_VERSION=", "MARKDOWNLINT_VERSION:"),
    "actionlint": ("ARG ACTIONLINT_VERSION=", "ACTIONLINT_VERSION:"),
    "gitleaks": ("ARG GITLEAKS_VERSION=", "GITLEAKS_VERSION:"),
}


def _pytest_job() -> str:
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    job = workflow.split("jobs:", 1)[1].split("\n  pytest:", 1)[1]
    nxt = re.search(r"\n  [a-zA-Z0-9_-]+:\n", job)
    return job[: nxt.start()] if nxt else job


@pytest.mark.parametrize("tool", sorted(ANALYZER_PINS))
def test_the_pytest_job_installs_every_pinned_analyzer(tool):
    _, ci_key = ANALYZER_PINS[tool]
    assert ci_key in _pytest_job(), (
        f"the pytest job does not install {tool}, so its failure proof will hard "
        f"fail in CI — which is correct, and the fix is the install step, not a "
        f"skip. Two of these were missing for the life of the repo and nothing "
        f"reported it, because a skipped analyzer and a clean one print the same."
    )


@pytest.mark.parametrize("tool", sorted(ANALYZER_PINS))
def test_analyzer_pins_agree_between_container_and_ci(tool):
    """Different versions is the subtler half.

    A CI runner on an older markdownlint passes the suite while enforcing fewer
    rules than the image does, so local, CI and container stop being the same
    gate without any of them going red.
    """
    docker_key, ci_key = ANALYZER_PINS[tool]
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    docker_pin = re.search(rf"^{re.escape(docker_key)}(\S+)", dockerfile, re.M)
    ci_pin = re.search(rf"^\s*{re.escape(ci_key)}\s*(\S+)", _pytest_job(), re.M)
    assert docker_pin, f"Dockerfile no longer declares {docker_key}"
    assert ci_pin, f"tests.yml no longer declares {ci_key}"
    assert docker_pin.group(1) == ci_pin.group(1), (
        f"{tool} pin drift: Dockerfile={docker_pin.group(1)}, CI={ci_pin.group(1)}"
    )


# --- ruff: pinned differently, so guarded differently (T005e) -----------------


def _yaml_step(job_text: str, step_name: str) -> str:
    """The full text of one `- name: <step_name>` block, up to the next step."""
    start = job_text.index(f"- name: {step_name}")
    rest = job_text[start + 1:]
    end = rest.find("\n      - name:")
    return rest if end == -1 else rest[:end]


def test_ruff_is_pinned_exactly_in_the_dev_extras():
    """ruff is a gate, and a floor (`>=`) lets two runners enforce two rule sets.

    It is pinned in pyproject rather than as a Dockerfile ARG because it is a
    Python package: CI and the image both install `.[dev]`, so one declaration
    reaches both and the ARG-vs-CI drift the tests above guard against cannot
    arise here by construction.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    # SCOPED to the dev extras. An unscoped search matches a `ruff==` line in
    # any table — [project.dependencies], a comment, another extra — so it would
    # pass while the extras that CI and the image install carry no ruff at all.
    section = re.search(
        r"^\[project\.optional-dependencies\]\s*\ndev\s*=\s*\[(.*?)^\]",
        pyproject, re.M | re.S,
    )
    assert section, "[project.optional-dependencies].dev not found in pyproject.toml"
    assert re.search(r'"ruff==\d+\.\d+\.\d+"', section.group(1)), (
        "ruff must be pinned with == inside [project.optional-dependencies].dev; "
        "a floor lets CI and the container run different rule sets, and a pin in "
        "another table never reaches either of them"
    )


def test_both_runners_install_the_dev_extras():
    """The pin only reaches a runner that installs it. If either consumer
    dropped `[dev]`, ruff would be absent, its analyzer would SKIP, and a
    skipped analyzer prints exactly like a clean one."""
    assert '-e ".[dev]"' in _pytest_job(), "the pytest job no longer installs the dev extras"
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert '-e ".[dev]"' in dockerfile, "the image no longer installs the dev extras"


def test_ci_lints_the_whole_repo_with_ruff():
    """The analyzer is diff-scoped; this step is what holds the repo baseline at
    zero. Without it the baseline can drift back up, and the argument for making
    the gate blocking rather than advisory quietly stops being true."""
    job = _pytest_job()
    assert "ruff check ." in job, "CI no longer lints the repository with ruff"
    # The WHOLE step, not the text before the command. `continue-on-error: true`
    # is conventionally written AFTER `run:`, which the first version of this
    # check could not see — and it also rejected an explicit `false`, which is
    # not warn-only at all. Both reported by review.
    step = _yaml_step(job, "Lint (ruff)")
    assert re.search(r"continue-on-error:\s*true", step) is None, (
        "the ruff step is warn-only; a report-only check over a clean baseline "
        "is where checkers go to die"
    )



def test_the_markdownlint_baseline_stays_at_zero():
    """T063a drove the residual from 177 to 0; this keeps it there.

    A residual is not self-maintaining — this one GREW from 176 to 316 while
    the spec-003 work added audits and quickstart sections, entirely from my
    own writing. Without an assertion, "drive it to zero" is a one-off cleanup
    that decays the moment anyone writes a doc.

    Asserted at zero rather than under a threshold: a threshold is a budget,
    and a budget gets spent.
    """
    import shutil
    import subprocess

    if shutil.which("markdownlint") is None:
        # NOT a skip — see tests/integration/test_static_analyzers.py for why a
        # skipped security-adjacent assertion is worse than a failing one.
        raise AssertionError(
            "markdownlint is not installed, so the baseline was not checked. "
            "Install it (npm i -g markdownlint-cli) rather than skipping: a "
            "gate that silently does not run reports clean."
        )
    # The dot-directory globs are LOAD-BEARING. `markdownlint .` does not
    # descend into `.claude/**` or `.specify/**`, so the first version of this
    # test asserted zero over a scope that silently excluded 12 files and 139
    # findings — an accidental exclusion and a deliberate one produce identical
    # clean output, which is this portfolio's founding defect, in its own
    # baseline guard. Vendored files are now excluded EXPLICITLY in
    # .markdownlintignore, with the reason, so this scope means what it says.
    proc = subprocess.run(
        ["markdownlint", ".", ".claude/**/*.md", ".specify/**/*.md"],
        cwd=REPO_ROOT, capture_output=True, text=True)
    findings = [ln for ln in (proc.stdout + proc.stderr).splitlines() if " MD" in ln]
    assert not findings, (
        f"{len(findings)} markdownlint finding(s) have crept back in:\n"
        + "\n".join(findings[:10])
    )


@pytest.mark.skipif(
    not (REPO_ROOT / ".claude").is_dir(),
    reason="no .claude/ surface — running in the public mirror, which "
    "deliberately excludes it (ADR-0010)",
)
def test_the_markdownlint_scope_actually_reaches_dot_directories():
    """Anti-vacuous companion: the scope must MATCH something.

    A glob that matches nothing looks exactly like a glob over clean files —
    the `scope-config-test` lesson, which this repo has now hit four times.
    So this asserts the dot-directory globs resolve to real files rather than
    trusting that they do.
    """
    import glob
    import os

    matched = glob.glob(os.path.join(REPO_ROOT, ".claude", "**", "*.md"), recursive=True)
    assert len(matched) >= 5, (
        f"the .claude glob matched {len(matched)} file(s); the scope has gone "
        f"stale and the zero baseline no longer covers what it claims"
    )
