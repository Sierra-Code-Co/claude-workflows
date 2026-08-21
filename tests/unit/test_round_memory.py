"""Round-N finding memory (T048, #20).

Suppressing a finding is the most dangerous thing this tool does, so the tests
are weighted toward the cases where it must NOT happen. The feature is only
worth having if "already dealt with" and "ignored" are told apart, and the only
evidence available for that is whether the flagged code moved.

The dangerous shape has its own test: a developer who ignores a finding must
still see it on round 2. A memory that suppressed on fingerprint alone would
make any finding disappear by running the tool twice.
"""
from __future__ import annotations

import pathlib

import pytest

from review_plan_v2.context import rounds
from review_plan_v2.types import Finding


def _finding(message: str = "commanderDedupKey needs a byte-stable comparator",
             file: str = "src/a.ts", line: int = 5, category: str = "correctness") -> Finding:
    return Finding(file=file, line=line, line_end=None, severity="actionable",
                   category=category, message=message, sources=["correctness"])


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("\n".join(f"line {i}" for i in range(1, 21)) + "\n")
    return tmp_path


# --- fingerprinting -----------------------------------------------------------


def test_the_same_finding_fingerprints_identically(repo):
    assert rounds.fingerprint(_finding()) == rounds.fingerprint(_finding())


def test_reworded_whitespace_and_line_numbers_do_not_change_identity():
    """Reviewers are non-deterministic. If a re-run's cosmetic rewording read as
    a new finding, the memory would never match anything and the feature would
    be a no-op that still looked implemented."""
    a = _finding("Uses localeCompare at line 12, affecting 8 rows")
    b = _finding("Uses  localeCompare   at line 14, affecting 9 rows")
    assert rounds.fingerprint(a) == rounds.fingerprint(b)


def test_a_different_message_is_a_different_finding():
    """Anti-vacuous control: normalising everything to one value would make the
    memory suppress every finding after round 1."""
    assert rounds.fingerprint(_finding("A problem")) != rounds.fingerprint(_finding("B problem"))


def test_the_same_message_in_a_different_file_is_a_different_finding():
    assert rounds.fingerprint(_finding(file="src/a.ts")) != rounds.fingerprint(_finding(file="src/b.ts"))


# --- the suppression rule -----------------------------------------------------


def test_a_finding_never_seen_before_is_kept(repo):
    kept, suppressed = rounds.partition(repo, [_finding()], prior=[])
    assert len(kept) == 1 and suppressed == []


def test_a_repeat_finding_whose_code_changed_is_suppressed(repo):
    """"Addressed": raised before, and the developer edited the flagged lines."""
    prior = rounds.record_for(repo, [_finding()], round_number=1)
    (repo / "src" / "a.ts").write_text(
        "\n".join(f"line {i}" if i != 5 else "line 5 — REWRITTEN" for i in range(1, 21)) + "\n"
    )
    kept, suppressed = rounds.partition(repo, [_finding()], prior)
    assert kept == []
    assert [s.file for s in suppressed] == ["src/a.ts"]
    assert suppressed[0].first_seen_round == 1


def test_a_repeat_finding_whose_code_is_UNCHANGED_is_still_shown(repo):
    """The dangerous case, and the reason condition 2 exists.

    A developer who ignores a finding must still see it. Suppressing on
    fingerprint alone would let anyone make a real finding disappear by running
    the tool a second time.
    """
    prior = rounds.record_for(repo, [_finding()], round_number=1)
    kept, suppressed = rounds.partition(repo, [_finding()], prior)
    assert len(kept) == 1, "an unaddressed finding was suppressed on its second sighting"
    assert suppressed == []


def test_an_edit_far_from_the_anchor_does_not_count_as_addressing_it(repo):
    """The anchor window is narrow on purpose. If any edit anywhere in the file
    counted, one unrelated change would clear every finding in that file."""
    prior = rounds.record_for(repo, [_finding(line=5)], round_number=1)
    (repo / "src" / "a.ts").write_text(
        "\n".join(f"line {i}" if i != 19 else "line 19 — unrelated" for i in range(1, 21)) + "\n"
    )
    kept, suppressed = rounds.partition(repo, [_finding(line=5)], prior)
    assert len(kept) == 1
    assert suppressed == []


def test_an_unreadable_anchor_keeps_the_finding(repo):
    """None is not a match. If the anchor cannot be read we cannot show the code
    changed, and the safe direction is always to show the finding."""
    prior = rounds.record_for(repo, [_finding(file="src/deleted.ts")], round_number=1)
    kept, suppressed = rounds.partition(repo, [_finding(file="src/deleted.ts")], prior)
    assert len(kept) == 1
    assert suppressed == []


def test_a_finding_from_an_earlier_round_reports_its_FIRST_sighting(repo):
    """"First raised in round 1" is the useful fact. Re-recording each round
    would walk it forward and lose it."""
    prior = (rounds.record_for(repo, [_finding()], round_number=1)
             + rounds.record_for(repo, [_finding()], round_number=3))
    (repo / "src" / "a.ts").write_text("totally different\n" * 20)
    _, suppressed = rounds.partition(repo, [_finding()], prior)
    # Exactly one. Two prior records for one fingerprint must yield ONE
    # suppression; emitting one per record would still satisfy `[0] == 1` while
    # printing the same finding to the operator twice.
    assert len(suppressed) == 1
    assert suppressed[0].first_seen_round == 1


# --- what the operator is told ------------------------------------------------


def test_suppressions_are_named_not_counted(repo):
    """The FR-011 rule applied here: a developer must be able to see exactly
    what was withheld, or the memory is indistinguishable from a reviewer that
    quietly stopped working."""
    lines = rounds.render_suppressions(
        [rounds.Suppression(file="src/a.ts", line=5, message="stale comparator", first_seen_round=1)]
    )
    joined = "\n".join(lines)
    assert "src/a.ts:5" in joined
    assert "stale comparator" in joined
    assert "--force-full" in joined, "a suppressed finding must be recoverable"


def test_rendering_nothing_produces_nothing(repo):
    assert rounds.render_suppressions([]) == []


# --- persistence hygiene ------------------------------------------------------


def test_records_carry_no_message_text(repo):
    """FR-015 bars message bodies from persisted telemetry, and this state file
    lives beside that telemetry. Hashes only."""
    secret = "AKIA-shaped thing in src/a.ts and a customer name"
    records = rounds.record_for(repo, [_finding(secret)], round_number=1)
    blob = repr(records)
    assert "customer" not in blob and "AKIA" not in blob
    assert records[0]["fingerprint"]


def test_history_older_than_the_window_is_dropped(repo):
    records = [{"fingerprint": "a", "anchor": "x", "round": 1},
               {"fingerprint": "b", "anchor": "y", "round": 9}]
    kept = rounds.trim(records, round_number=9, max_rounds=5)
    assert [r["fingerprint"] for r in kept] == ["b"]


def test_malformed_prior_records_are_ignored_not_fatal(repo):
    """The state file is shared with other tooling and edited by hand during
    debugging. A junk row must not take the review down."""
    kept, suppressed = rounds.partition(
        repo, [_finding()], prior=[{"no": "fingerprint"}, "not a dict", {"fingerprint": 42}]
    )
    assert len(kept) == 1
    assert suppressed == []


def test_history_records_what_was_RAISED_not_what_survived_suppression(repo):
    """Why a suppressed finding is carried forward rather than re-recorded.

    Two ways to get this wrong, and the first draft of this module had the
    second:

      * drop it from the history entirely — it ages out and reappears as though
        never raised;
      * re-record it with the CURRENT anchor — a round later the anchor matches,
        so it reads as unaddressed and comes back. The feature undoes itself on
        run three, and no two-round end-to-end test can see it.

    Carrying the record forward keeps the original anchor (the evidence the code
    moved) and refreshes only recency.
    """
    finding = _finding()
    history = rounds.record_for(repo, [finding], round_number=1)

    (repo / "src" / "a.ts").write_text(
        "\n".join(f"line {i}" if i != 5 else "line 5 — REWRITTEN" for i in range(1, 21)) + "\n"
    )
    visible, suppressed = rounds.partition(repo, [finding], history)
    assert suppressed and visible == []

    # Round 2 refreshes the RECENCY of the suppressed record and keeps its
    # original anchor, then trims. `max_rounds=1` compresses the window so the
    # ageing behaviour is observable in one step.
    history = rounds.trim(rounds.carry_forward(history, suppressed, 2), 2, max_rounds=1)
    _, still_suppressed = rounds.partition(repo, [finding], history)
    assert still_suppressed, (
        "the sighting aged out of the window, so an addressed finding came back "
        "as though it were new"
    )
    assert still_suppressed[0].first_seen_round == 1, (
        "carrying the record forward overwrote when it was FIRST raised"
    )

# --- malformed input must fail toward SHOWING the finding (review-found) -------


@pytest.mark.parametrize("bad_anchor", [123, "", None, [], {"a": 1}])
def test_a_malformed_anchor_does_not_suppress(repo, bad_anchor):
    """The dangerous direction, reachable from a hand-edited state file.

    A junk anchor can never EQUAL the current hash, so a comparison that only
    guards `None` takes the "code changed" branch and hides a finding nobody
    addressed. Malformed input must fail toward showing.
    """
    prior = [{"fingerprint": rounds.fingerprint(_finding()), "anchor": bad_anchor,
              "first_round": 1, "round": 1}]
    kept, suppressed = rounds.partition(repo, [_finding()], prior)
    assert len(kept) == 1, f"a {type(bad_anchor).__name__} anchor suppressed a finding"
    assert suppressed == []


@pytest.mark.parametrize("row", [
    "not a dict", 42, None,
    {"fingerprint": "a", "round": "not-an-int"},
    {"fingerprint": "a", "round": None},
    {"fingerprint": "a"},
])
def test_trim_tolerates_the_same_junk_rows_partition_does(row):
    """The two functions disagreed about what a valid record is: `partition`
    skipped a hand-edited row and `trim` raised on it, in a file whose docstring
    says it is shared and hand-edited."""
    kept = rounds.trim([row, {"fingerprint": "b", "round": 9}], round_number=9, max_rounds=5)
    assert {r["fingerprint"] for r in kept} == {"b"}


def test_a_file_deleted_after_being_recorded_keeps_its_finding(repo):
    """"Fixed by deleting the file" is a real path, and the prior anchor exists
    while the current one cannot be computed. Unknown is not "changed"."""
    prior = rounds.record_for(repo, [_finding()], round_number=1)
    assert prior[0]["anchor"] is not None, "the fixture did not record an anchor"
    (repo / "src" / "a.ts").unlink()
    kept, suppressed = rounds.partition(repo, [_finding()], prior)
    assert len(kept) == 1
    assert suppressed == []


@pytest.mark.parametrize("escape", ["/etc/passwd", "../../../../../../etc/passwd"])
def test_anchor_hash_refuses_a_path_outside_the_repo(repo, escape):
    """`Path("/repo") / "/etc/passwd"` is `/etc/passwd` — pathlib discards the
    left side when the right is absolute. The path comes from reviewer output,
    which is model-controlled."""
    assert rounds.anchor_hash(repo, escape, 1) is None
