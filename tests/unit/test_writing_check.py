"""The writing-check skill: prose-lint.sh, prose-check.sh and the phrase list.

Every red, green, tool-error and HTML case Jason proved by hand on 2026-11-16,
with neutral file names in place of the engagement's (spec 004 FR-022), plus
the slop-guard calibration shapes seen on real work as smoke tests.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# WRITING_CHECK_SKILL_DIR points the suite at a scratch copy, so a guard can be
# broken in the copy to watch its test go red without touching the real skill.
SKILL = Path(os.environ.get("WRITING_CHECK_SKILL_DIR") or REPO / "dotfiles/claude/skills/writing-check")
LINT = SKILL / "scripts/prose-lint.sh"
CHECK = SKILL / "scripts/prose-check.sh"
PHRASES = SKILL / "banned-phrases.txt"
PYZ = SKILL / "vendor/slop-guard/slop-guard.pyz"


def python311() -> str:
    """An interpreter that can run the packed slop-guard (3.11+), or skip.

    The repo itself supports 3.10, so the test interpreter may be too old to
    run the pack even when a newer Python is installed next to it.
    """
    if sys.version_info >= (3, 11):
        return sys.executable
    for name in ("python3.14", "python3.13", "python3.12", "python3.11"):
        found = shutil.which(name)
        if found:
            return found
    pytest.skip("no Python 3.11+ available to run the packed slop-guard")

RED = [
    "Five things you may want to know:",
    "4. Two blanks only you can fill.",
    "One more thing you may run into: it is off.",
    "These are the three checks. Name them once.",
    "Say it once, plainly.",
    "That is the lesson: read what it used.",
    "Nobody asked it to count.",
    "That is the difference between a variance and a story.",
    "which is exactly the lesson in checking.",
    "It ran -- then stopped.",
    "It ran – then stopped.",
    "For table helpers. Built by build_sheets.py, so every number matches.",
    "See helper-key-draft.md.",
    "Why this matters.",
    "It is not a tool. It is a habit.",
    "Not a detail. A design decision.",
    "Ultimately, it comes down to trust.",
    # not among the 2026-11-16 hand cases, added so the built-in checks are covered too
    "It ran — then stopped.",
    "It ran &mdash; then stopped.",
    "It's not a report, it's a habit.",
    "Not only fast but cheap.",
    "Two spaces.  Here.",
]

GREEN = [
    "The basics sheet has a blank line.",
    "Switch Web search off if it should use only your files.",
    "The title has to be cleared first.",
    "The helper key is pages 35 to 40.",
    "Name them in the report header.",
    "Please name the file.",
    "Read the three checks out once.",
    "a comment -->",
    "--navy: #002855;",
    "July 31–August 6",
    "Attach weekly-report-2026-07-30.docx and time-standard-report.xlsx.",
    "Save it as .docx, .xlsx or .pdf.",
]


def run(cmd, *, env=None, cwd=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env, cwd=cwd)


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def lint_env(**extra):
    env = {k: v for k, v in os.environ.items() if k != "PROSE_LINT_PHRASES"}
    env.update(extra)
    return env


# --------------------------------------------------------------- prose-lint ---

@pytest.mark.parametrize("text", RED)
def test_red_case_is_flagged(tmp_path, text):
    r = run(["bash", LINT, write(tmp_path, "d.txt", text + "\n")], env=lint_env())
    assert r.returncode == 1, (text, r.stdout, r.stderr)
    assert "check(s) hit" in r.stdout


@pytest.mark.parametrize("text", GREEN)
def test_green_case_is_clean(tmp_path, text):
    r = run(["bash", LINT, write(tmp_path, "d.txt", text + "\n")], env=lint_env())
    assert r.returncode == 0, (text, r.stdout, r.stderr)
    m = re.search(r"prose-lint: clean \((\d+) phrases checked\)", r.stdout)
    assert m and int(m.group(1)) > 200, r.stdout


def test_last_line_without_newline_is_checked(tmp_path):
    r = run(["bash", LINT, write(tmp_path, "d.txt", "ok line\nOne more thing.")], env=lint_env())
    assert r.returncode == 1


def test_lint_finds_its_list_when_called_by_relative_path_with_cdpath(tmp_path):
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    rel = os.path.relpath(LINT, SKILL.parent)
    r = run(["bash", rel, doc], env=lint_env(CDPATH=f".:{tmp_path}"), cwd=SKILL.parent)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_names_file_flags_a_name(tmp_path):
    names = write(tmp_path, "names.txt", "Acme Widgets\n")
    doc = write(tmp_path, "d.txt", "We met the acme widgets team.\n")
    r = run(["bash", LINT, doc, names], env=lint_env())
    assert r.returncode == 1 and "banned name: Acme Widgets" in r.stdout


@pytest.mark.parametrize(
    "case",
    ["missing_list", "bad_regex", "comments_only", "empty_list", "missing_doc", "empty_doc", "missing_names",
     "names_is_a_directory"],
)
def test_lint_tool_errors_exit_2(tmp_path, case):
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    env = lint_env()
    args = ["bash", LINT, doc]
    if case == "missing_list":
        env["PROSE_LINT_PHRASES"] = "/nonexistent/banned-phrases.txt"
    elif case == "bad_regex":
        env["PROSE_LINT_PHRASES"] = str(write(tmp_path, "l.txt", "\\bplain\\b\nonly you (can\n"))
    elif case == "comments_only":
        env["PROSE_LINT_PHRASES"] = str(write(tmp_path, "l.txt", "# just a comment\n\n# another\n"))
    elif case == "empty_list":
        env["PROSE_LINT_PHRASES"] = str(write(tmp_path, "l.txt", ""))
    elif case == "missing_doc":
        args = ["bash", LINT, tmp_path / "nope.txt"]
    elif case == "empty_doc":
        args = ["bash", LINT, write(tmp_path, "e.txt", "  \n\n")]
    elif case == "names_is_a_directory":
        # -r is true for a readable directory, and the read loop then fails
        # quietly; without the regular-file check this ran clean with no names checked.
        (tmp_path / "names-dir").mkdir()
        args = ["bash", LINT, doc, tmp_path / "names-dir"]
    elif case == "missing_names":
        args = ["bash", LINT, doc, tmp_path / "no-names.txt"]
    r = run(args, env=env)
    assert r.returncode == 2, (case, r.stdout, r.stderr)
    assert "clean" not in r.stdout


def test_every_phrase_compiles_and_list_is_not_trivially_small():
    rules = [ln for ln in PHRASES.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(rules) > 200
    for rx in rules:
        # grep -E is the real engine; ask it directly rather than trusting Python's re.
        r = subprocess.run(["grep", "-qiE", "-e", rx], input="x", capture_output=True, text=True)
        assert r.returncode in (0, 1), (rx, r.stderr)


# --------------------------------------------- phrase list covers slop-guard ---

def _slop_guard_literals() -> dict[str, list[str]]:
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1])\n"
        "import slop_guard.rules.word.slop_word as w\n"
        "import slop_guard.rules.sentence.slop_phrase as a\n"
        "import slop_guard.rules.sentence.weasel_phrase as b\n"
        "import slop_guard.rules.sentence.tone_marker as c\n"
        "import slop_guard.rules.sentence.ai_disclosure as d\n"
        "print(json.dumps({'word': list(w._ALL_SLOP_WORDS), 'phrase': list(a._SLOP_PHRASES_LITERAL),"
        " 'weasel': list(b._WEASEL_LITERALS),"
        " 'tone': list(c._META_COMM_LITERALS) + list(c._FALSE_NARRATIVITY_LITERALS),"
        " 'ai': list(d._AI_DISCLOSURE_LITERALS)}))\n"
    )
    r = subprocess.run([python311(), "-I", "-c", code, str(PYZ)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json

    out = json.loads(r.stdout)
    assert sum(len(v) for v in out.values()) > 150, "slop-guard lists came back nearly empty"
    return out


def uncovered_slop_guard_literals(phrase_text: str) -> list[str]:
    pats, by_hand = [], set()
    for line in phrase_text.splitlines():
        if line.startswith("# read-by-hand:"):
            by_hand |= {x.strip().lower() for x in line.split(":", 1)[1].split(",") if x.strip()}
        elif line.strip() and not line.startswith("#"):
            pats.append(re.compile(line.replace("[[:space:]]", r"\s"), re.I))
    missing = []
    for kind, words in _slop_guard_literals().items():
        for word in words:
            if word.lower() not in by_hand and not any(p.search(word) for p in pats):
                missing.append(f"{kind}: {word}")
    return missing


def test_every_slop_guard_literal_is_a_pattern_or_read_by_hand():
    missing = uncovered_slop_guard_literals(PHRASES.read_text(encoding="utf-8"))
    assert not missing, "classify these in banned-phrases.txt:\n" + "\n".join(missing)


def test_coverage_check_fails_when_a_word_is_dropped():
    """Principle II: the coverage test must be able to go red."""
    text = PHRASES.read_text(encoding="utf-8").replace("|odyssey|", "|")
    assert "word: odyssey" in uncovered_slop_guard_literals(text)


# -------------------------------------------------------------- prose-check ---

def check_env(path: str | None = None, **extra):
    env = lint_env(**extra)
    env["PROSE_CHECK_PYTHON"] = extra.get("PROSE_CHECK_PYTHON") or python311()
    if path is not None:
        env["PATH"] = path
    return env


def no_sg_path(tmp_path: Path) -> str:
    """A PATH with bash, grep and friends but no `sg`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for tool in ("bash", "grep", "dirname", "mktemp", "rm", "cat"):
        found = shutil.which(tool)
        assert found, tool
        (bindir / tool).symlink_to(found)
    return str(bindir)


def test_check_runs_packed_slop_guard_with_no_sg_on_path(tmp_path):
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line. Fill it in before the session starts.\n")
    r = run(["bash", CHECK, doc], env=check_env(no_sg_path(tmp_path)))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "slop-guard.pyz" in r.stdout and "/100 [" in r.stdout and "prose-check: pass" in r.stdout


def test_check_flags_red_text(tmp_path):
    doc = write(tmp_path, "d.txt", "It is not a tool. It is a habit. Name them once.\n")
    r = run(["bash", CHECK, doc], env=check_env(no_sg_path(tmp_path)))
    assert r.returncode == 1 and "FLAGGED" in r.stdout


def test_check_exits_2_with_no_runnable_slop_guard(tmp_path):
    # Copy the skill without its vendor folder, and hide sg.
    skill = tmp_path / "skill"
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("vendor"))
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    r = run(["bash", skill / "scripts/prose-check.sh", doc], env=check_env(no_sg_path(tmp_path)))
    assert r.returncode == 2 and "no runnable slop-guard" in r.stderr


def test_check_works_when_called_by_relative_path_with_cdpath_exported(tmp_path):
    """Jason's shells export CDPATH; then `cd relative/dir` prints and breaks $(cd ... && pwd)."""
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line. Fill it in before the session starts.\n")
    env = check_env(no_sg_path(tmp_path), CDPATH=f".:{tmp_path}")
    rel = os.path.relpath(CHECK, SKILL.parent)
    r = run(["bash", rel, doc], env=env, cwd=SKILL.parent)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "prose-lint: clean" in r.stdout


def test_check_refuses_an_sg_that_is_not_slop_guard(tmp_path):
    """`sg` is also ast-grep's old name; on Homebrew it is often first on PATH."""
    skill = tmp_path / "skill"
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("vendor"))
    path = no_sg_path(tmp_path)
    fake = Path(path) / "sg"
    fake.write_text("#!/bin/bash\necho 'Usage: ast-grep [OPTIONS] <COMMAND>'\nexit 0\n")
    fake.chmod(0o755)
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    r = run(["bash", skill / "scripts/prose-check.sh", doc], env=check_env(path))
    assert r.returncode == 2
    assert "not slop-guard" in r.stderr and "ast-grep" not in r.stdout


def test_check_exits_2_on_python_too_old(tmp_path):
    fake = tmp_path / "oldpy"
    fake.write_text('#!/bin/bash\nif [ "$1" = "-c" ]; then case "$2" in *print*) echo 3.9;; *) exit 1;; esac; fi\nexit 1\n')
    fake.chmod(0o755)
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    r = run(["bash", CHECK, doc], env=check_env(no_sg_path(tmp_path), PROSE_CHECK_PYTHON=str(fake)))
    assert r.returncode == 2
    assert "3.9" in r.stderr and "3.11" in r.stderr


def test_check_exits_2_when_slop_guard_crashes(tmp_path):
    """A traceback exits 1 too; without a score line it must not read as 'flagged'."""
    skill = tmp_path / "skill"
    shutil.copytree(SKILL, skill)
    (skill / "vendor/slop-guard/slop-guard.pyz").write_text("raise SystemExit(1)\n")
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    r = run(["bash", skill / "scripts/prose-check.sh", doc], env=check_env(no_sg_path(tmp_path)))
    assert r.returncode == 2 and "no score" in r.stderr


@pytest.mark.parametrize("case", ["missing_doc", "empty_doc", "bad_threshold", "lint_list_missing"])
def test_check_tool_errors_exit_2(tmp_path, case):
    doc = write(tmp_path, "d.txt", "The basics sheet has a blank line.\n")
    env = check_env(no_sg_path(tmp_path))
    args = ["bash", CHECK, doc]
    if case == "missing_doc":
        args = ["bash", CHECK, tmp_path / "nope.txt"]
    elif case == "empty_doc":
        args = ["bash", CHECK, write(tmp_path, "e.html", "<html><!-- only a comment --></html>")]
    elif case == "bad_threshold":
        args = ["bash", CHECK, doc, "-t", "eighty"]
    elif case == "lint_list_missing":
        env["PROSE_LINT_PHRASES"] = "/nonexistent"
    r = run(args, env=env)
    assert r.returncode == 2, (case, r.stdout, r.stderr)
    assert "prose-check: pass" not in r.stdout


def test_html_comment_file_name_is_ignored_but_paragraph_is_not(tmp_path):
    body = "<p>The basics sheet has a blank line. Fill it in before the session starts.</p>"
    hidden = write(tmp_path, "a.html", f"<html><body><!-- Built by build_sheets.py -->{body}</body></html>")
    shown = write(tmp_path, "b.html", f"<html><body><p>Built by build_sheets.py.</p>{body}</body></html>")
    env = check_env(no_sg_path(tmp_path))
    r1 = run(["bash", CHECK, hidden], env=env)
    r2 = run(["bash", CHECK, shown], env=env)
    assert r1.returncode == 0, (r1.stdout, r1.stderr)
    assert r2.returncode == 1 and "build_sheets.py" in r2.stdout


def test_html_css_and_script_are_not_checked(tmp_path):
    html = (
        "<html><head><style>:root { --navy: #002855; } /* robust */</style>"
        "<script>// leverage</script></head><body><p>The basics sheet has a blank line.</p></body></html>"
    )
    r = run(["bash", CHECK, write(tmp_path, "c.html", html)], env=check_env(no_sg_path(tmp_path)))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_html_temp_file_is_removed(tmp_path):
    tmpdir = tmp_path / "t"
    tmpdir.mkdir()
    html = write(tmp_path, "c.html", "<p>The basics sheet has a blank line.</p>")
    run(["bash", CHECK, html], env=check_env(no_sg_path(tmp_path), TMPDIR=str(tmpdir)))
    assert list(tmpdir.iterdir()) == []


# ------------------------------------------- slop-guard calibration smoke tests ---

BULLET_EMAIL = (
    "Hi Sam,\n\nThanks for the call. Notes from today:\n\n"
    + "".join(f"- Item {i}: the sheet for week {i} goes out on Monday.\n" for i in range(1, 8))
    + "\nTalk soon,\nJason\n"
)
PARAGRAPH_EMAIL = (
    "Hi Sam,\n\nThanks for the call. The sheets for weeks one to seven go out on Monday, "
    "one per week, in the shared folder you set up. I will send the first two today so your "
    "team can try them before the session.\n\nTalk soon,\nJason\n"
)


def score(tmp_path: Path, name: str, text: str) -> int:
    p = write(tmp_path, name, text)
    r = run([python311(), "-I", PYZ, p])
    m = re.search(r": (\d+)/100 \[", r.stdout)
    assert m, (r.stdout, r.stderr)
    return int(m.group(1))


def test_calibration_bullets_cost_more_than_paragraphs(tmp_path):
    bullets = score(tmp_path, "b.txt", BULLET_EMAIL)
    paras = score(tmp_path, "p.txt", PARAGRAPH_EMAIL)
    assert bullets < 80 <= paras, (bullets, paras)


def test_calibration_one_colon_hurts_a_short_note(tmp_path):
    base = "The report goes out on Monday. Read the totals first and check the dates against the calendar."
    with_colon = score(tmp_path, "c.txt", base.replace("Read the totals first", "Here is the order: read the totals first"))
    without = score(tmp_path, "n.txt", base)
    assert with_colon < without, (with_colon, without)
