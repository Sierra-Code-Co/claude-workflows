"""path_filters: CodeRabbit semantics, real glob matching, readable direction (T010b).

Three defects lived here at once and each hid the next: the `!` was never
stripped (every exclusion inert), bare patterns excluded instead of including
(the inverse of the config file's own convention), and the only feedback was a
COUNT — which cannot express direction, so neither of the first two was visible.

The negatives below are derived from those three, plus the glob semantics
`fnmatch` gets wrong.
"""
from __future__ import annotations

import pytest

from review_plan_v2.path_filter import (
    FilterError,
    apply_filters,
    matches,
    split_patterns,
)


# --- defect 1: the `!` was never stripped ------------------------------------


def test_a_bang_pattern_excludes():
    """`'!references/**'` in .coderabbit.yaml had never excluded anything: with
    the `!` intact it could only match a path literally starting with `!`."""
    d = apply_filters(["references/a.md", "scripts/b.py"], ["!references/**"])
    assert d.kept == ("scripts/b.py",)
    assert d.dropped == (("references/a.md", "!references/**"),)


def test_the_bang_is_not_matched_literally():
    assert not matches("!references/a.md", "references/**")
    assert matches("references/a.md", "references/**")


# --- defect 2: bare patterns were INVERTED -----------------------------------


def test_a_bare_pattern_includes():
    """The measured inversion: `["scripts/**"]` used to review the 17 NON-scripts
    files out of 30. CodeRabbit's convention — and the one the config is written
    in — is that a bare pattern narrows TO the match."""
    d = apply_filters(["scripts/a.py", "tests/b.py", "docs/c.md"], ["scripts/**"])
    assert d.kept == ("scripts/a.py",)
    assert {p for p, _ in d.dropped} == {"tests/b.py", "docs/c.md"}


def test_only_exclusions_keeps_everything_else():
    """Every real config in this fleet is exclusions-only, so this is the
    behaviour the file always claimed and never had."""
    d = apply_filters(["a.py", "b.png", "references/c.md"],
                      ["!**/*.png", "!references/**"])
    assert d.kept == ("a.py",)


def test_includes_and_excludes_compose():
    d = apply_filters(
        ["scripts/a.py", "scripts/vendor/b.py", "tests/c.py"],
        ["scripts/**", "!scripts/vendor/**"],
    )
    assert d.kept == ("scripts/a.py",)


def test_no_patterns_keeps_everything():
    d = apply_filters(["a.py", "b.py"], [])
    assert d.kept == ("a.py", "b.py")
    assert not d.active


# --- the glob semantics fnmatch gets wrong -----------------------------------


@pytest.mark.parametrize("path, pattern, expected", [
    # `**/` must match ZERO segments. fnmatch's translation requires the slash,
    # so a top-level PNG slipped past `!**/*.png` even once the `!` was handled.
    ("a.png", "**/*.png", True),
    ("x/a.png", "**/*.png", True),
    ("x/y/z/a.png", "**/*.png", True),
    # A single `*` must NOT cross a separator. fnmatch's `*` does, which would
    # make `scripts/*.py` silently match `scripts/vendor/deep.py`.
    ("scripts/deep/a.py", "scripts/*.py", False),
    ("scripts/a.py", "scripts/*.py", True),
    ("scripts/deep/a.py", "scripts/**/*.py", True),
    ("references/a.md", "references/**", True),
    ("references", "references/**", False),
    ("a/b.md", "?/b.md", True),
    ("ab/b.md", "?/b.md", False),
])
def test_glob_semantics(path, pattern, expected):
    assert matches(path, pattern) is expected


# --- defect 3: a count cannot express direction ------------------------------


def test_the_decision_names_the_pattern_that_dropped_each_file():
    """"would review 17 files" is equally true of keeping 17 and dropping 17.
    That ambiguity is why an inverted filter survived, and why I published a
    wrong claim off a dry-run count. The decision has to say WHICH rule fired."""
    d = apply_filters(["a.png", "b.py", "references/c.md"],
                      ["!**/*.png", "!references/**"])
    by_pattern = d.dropped_by_pattern()
    assert by_pattern["!**/*.png"] == ["a.png"]
    assert by_pattern["!references/**"] == ["references/c.md"]


def test_the_summary_states_direction_not_just_magnitude():
    d = apply_filters(["scripts/a.py", "tests/b.py"], ["scripts/**"])
    s = d.summary()
    assert "reviewing 1 of 2" in s
    assert "include=['scripts/**']" in s


def test_summary_is_explicit_when_no_filters_are_configured():
    assert "none configured" in apply_filters(["a.py"], []).summary()


# --- malformed patterns are rejected, never ignored --------------------------


@pytest.mark.parametrize("bad", ["!", "! ", "", "   ", None, 42])
def test_unusable_patterns_raise(bad):
    with pytest.raises(FilterError):
        split_patterns([bad])


def test_a_usable_pattern_set_parses():
    """Anti-vacuous control: rejection must not be the only outcome."""
    inc, exc = split_patterns(["scripts/**", "!tests/**"])
    assert inc == ["scripts/**"] and exc == ["tests/**"]


def test_this_repos_own_config_is_all_exclusions_and_now_bites():
    """The nine patterns in .coderabbit.yaml, which had never filtered anything.

    Pinned here as a fixture rather than read from disk: the point is that these
    SHAPES work, and a test that reads the live config would go quiet the moment
    someone edited it.
    """
    patterns = ["!**/*.png", "!**/*.jpg", "!**/*.webp", "!**/*.gif",
                "!.claude/cache/**", "!.claude/projects/**",
                "!.claude/shell-snapshots/**", "!.claude/todos/**",
                "!references/**"]
    paths = ["a.png", "deep/b.jpg", ".claude/projects/x.jsonl",
             "references/r.md", "scripts/keep.py", "README.md"]
    d = apply_filters(paths, patterns)
    assert d.kept == ("scripts/keep.py", "README.md")
    assert len(d.dropped) == 4


# --- unsupported glob syntax is rejected, not mistranslated -------------------


@pytest.mark.parametrize("pattern", [
    "*.[jt]s", "src/**/*.{js,ts}", "a\\*b", "!*.[jt]s",
])
def test_unsupported_glob_syntax_is_rejected_loudly(pattern):
    """globset has character classes, brace alternation and escapes; this
    translator does not.

    Escaping them literally — the default in the `else` branch — makes
    `*.[jt]s` match a file named exactly `*.[jt]s` and nothing else. A pattern
    that quietly matches nothing is the same defect as the inert `!` this module
    was written to fix, so it fails at parse time instead.
    """
    with pytest.raises(FilterError, match="does not support"):
        split_patterns([pattern])


def test_supported_syntax_is_not_over_rejected():
    """Anti-vacuous control: rejection must not swallow the patterns people
    actually write."""
    inc, exc = split_patterns(["scripts/**", "**/*.png", "src/*.py", "a?c/**"])
    assert len(inc) == 4 and not exc


@pytest.mark.parametrize("pattern", ["a**b", "src/a**/x", "**.py"])
def test_double_star_must_be_a_whole_path_component(pattern):
    """globset treats `**` as recursive only as a full component; `a**b` is not.

    This translator would read it as `.*` and match MORE than the syntax it is
    written in promises — a pattern quietly behaving differently from its own
    notation, which is the family of bug this module exists to close.
    """
    with pytest.raises(FilterError, match="whole component"):
        split_patterns([pattern])


@pytest.mark.parametrize("pattern", ["**", "a/**", "**/b", "a/**/b", "**/*.png"])
def test_standalone_double_star_is_accepted(pattern):
    """Anti-vacuous control: the component check must not reject the forms every
    real config uses."""
    assert split_patterns([pattern])[0] == [pattern]
