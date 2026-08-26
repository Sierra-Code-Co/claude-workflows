"""Unit test for gitleaks line-overlap filter."""
from __future__ import annotations

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.analyzers.gitleaks import filter_to_diff_lines
from review_plan_v2.types import FileChange, Finding


def mkfc(path="src/a.py", added=()):
    return FileChange(path=path, is_binary=False, is_renamed_from=None,
                      added_lines=added, diff_text="", language="python")


def mkf(path="src/a.py", line=10):
    return Finding(file=path, line=line, line_end=None, severity="actionable",
                   category="secrets", message="x", sources=["gitleaks"])


class GitleaksOverlapTests(unittest.TestCase):
    def test_finding_in_added_range_kept(self):
        files = [mkfc(added=((10, 20),))]
        out = filter_to_diff_lines([mkf(line=15)], files)
        self.assertEqual(len(out), 1)

    def test_finding_outside_range_dropped(self):
        files = [mkfc(added=((10, 20),))]
        out = filter_to_diff_lines([mkf(line=5)], files)
        self.assertEqual(out, [])

    def test_finding_at_range_boundary_kept(self):
        files = [mkfc(added=((10, 20),))]
        out_start = filter_to_diff_lines([mkf(line=10)], files)
        out_end = filter_to_diff_lines([mkf(line=20)], files)
        self.assertEqual(len(out_start), 1)
        self.assertEqual(len(out_end), 1)

    def test_finding_in_unknown_file_dropped(self):
        files = [mkfc(path="src/a.py", added=((1, 100),))]
        out = filter_to_diff_lines([mkf(path="src/other.py", line=5)], files)
        self.assertEqual(out, [])

    def test_multiple_ranges(self):
        files = [mkfc(added=((1, 5), (50, 60), (100, 110)))]
        out = filter_to_diff_lines([mkf(line=55), mkf(line=200)], files)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].line, 55)


# --- T005j: a file gitleaks never scanned is NOT a clean file -----------------


def _fc_g(path: str, added=((1, 5),)):
    from review_plan_v2.types import FileChange
    return FileChange(path=path, is_binary=False, is_renamed_from=None,
                      added_lines=tuple(added), diff_text="", language="py")


def test_a_file_with_added_lines_that_is_missing_is_reported_not_skipped(tmp_path):
    """The dangerous half of T005j.

    New content exists in the diff and nothing scanned it. Zero secret findings
    for that file is byte-identical to "read it and it was clean", which is how
    the most expensive silence in this portfolio stayed invisible.
    """
    from review_plan_v2.analyzers.gitleaks import GitleaksAnalyzer

    res = GitleaksAnalyzer().run([_fc_g("never/written.py")], workdir=str(tmp_path))
    assert res.not_scanned, "a file with added lines was silently skipped"
    assert res.coverage_is_complete is False
    gaps = "\n".join(res.coverage_gaps())
    assert "never/written.py" in gaps
    assert "did NOT scan" in gaps


def test_a_DELETED_file_is_not_reported_as_a_gap(tmp_path):
    """Anti-vacuous, and what keeps the banner readable.

    A deletion has no added lines, and gitleaks only reports secrets on ADDED
    lines — so there was nothing to find and the skip is correct. Reporting it
    would fire on most diffs, and a banner that fires every run is one nobody
    reads by the third week.
    """
    from review_plan_v2.analyzers.gitleaks import GitleaksAnalyzer

    res = GitleaksAnalyzer().run([_fc_g("was/deleted.py", added=())], workdir=str(tmp_path))
    assert res.not_scanned == []
    assert res.coverage_is_complete is True


def test_a_scanned_file_produces_no_gap(tmp_path):
    """Anti-vacuous the other way: an implementation reporting every file as
    unscanned would satisfy the first test while making the banner meaningless."""
    from review_plan_v2.analyzers.gitleaks import GitleaksAnalyzer

    (tmp_path / "real.py").write_text("x = 1\n")
    res = GitleaksAnalyzer().run([_fc_g("real.py")], workdir=str(tmp_path))
    assert res.not_scanned == []
    assert res.coverage_is_complete is True


if __name__ == "__main__":
    unittest.main()
