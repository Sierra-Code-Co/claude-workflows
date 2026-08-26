"""Aggregator dedup, confidence promotion, severity demotion."""
from __future__ import annotations

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.aggregator import aggregate
from review_plan_v2.types import Finding, PathInstruction


def mkf(file="src/a.ts", line=10, line_end=None, severity="actionable",
        category="security", message="m", source="security") -> Finding:
    return Finding(file=file, line=line, line_end=line_end, severity=severity,
                   category=category, message=message, sources=[source])


class AggregatorTests(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(aggregate([]), [])

    def test_single_finding_passes_through(self):
        f = mkf()
        out = aggregate([[f]])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].sources, ["security"])
        self.assertEqual(out[0].confidence, "single-source")

    def test_dedup_same_line_promotes_confidence(self):
        a = mkf(source="security")
        b = mkf(source="correctness")
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0].sources), {"security", "correctness"})
        self.assertEqual(out[0].confidence, "high-confidence")

    def test_dedup_within_window(self):
        a = mkf(line=10)
        b = mkf(line=13)  # within ±5 default
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 1)

    def test_no_dedup_outside_window(self):
        a = mkf(line=10)
        b = mkf(line=20)
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 2)

    def test_no_dedup_different_category(self):
        a = mkf(category="security")
        b = mkf(category="correctness")
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 2)

    def test_no_dedup_different_file(self):
        a = mkf(file="src/a.ts")
        b = mkf(file="src/b.ts")
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 2)

    def test_actionable_wins_over_nit_on_merge(self):
        a = mkf(severity="nit", source="x")
        b = mkf(severity="actionable", source="y")
        out = aggregate([[a], [b]])
        self.assertEqual(out[0].severity, "actionable")

    def test_path_instructions_demote_soft_category(self):
        f = mkf(file="docs/README.md", category="prose", severity="nit")
        pi = [PathInstruction(path_glob="docs/*.md", instructions="skip prose nits")]
        out = aggregate([[f]], path_instructions=pi)
        self.assertEqual(out[0].severity, "info")

    def test_path_instructions_do_not_demote_hard_category(self):
        f = mkf(file="docs/README.md", category="security", severity="actionable")
        pi = [PathInstruction(path_glob="docs/*.md", instructions="skip prose nits")]
        out = aggregate([[f]], path_instructions=pi)
        self.assertEqual(out[0].severity, "actionable")

    def test_path_instructions_no_keyword_no_demote(self):
        f = mkf(file="docs/README.md", category="prose", severity="nit")
        pi = [PathInstruction(path_glob="docs/*.md", instructions="favor concise prose")]
        out = aggregate([[f]], path_instructions=pi)
        self.assertEqual(out[0].severity, "nit")

    def test_findings_sorted_by_severity_then_file_line(self):
        # Severity tier wins over file order: an actionable in b.ts comes before nits in a.ts.
        a = mkf(file="b.ts", line=5, severity="actionable")
        b = mkf(file="a.ts", line=10, severity="nit")
        c = mkf(file="a.ts", line=20, severity="info")
        out = aggregate([[a], [b], [c]])
        self.assertEqual([(x.file, x.line, x.severity) for x in out],
                         [("b.ts", 5, "actionable"), ("a.ts", 10, "nit"), ("a.ts", 20, "info")])

    def test_findings_within_same_tier_sorted_by_file_line(self):
        a = mkf(file="b.ts", line=5)
        b = mkf(file="a.ts", line=10)
        c = mkf(file="a.ts", line=20)
        out = aggregate([[a], [b], [c]])
        self.assertEqual([(x.file, x.line) for x in out], [("a.ts", 10), ("a.ts", 20), ("b.ts", 5)])

    def test_custom_dedup_window(self):
        a = mkf(line=10)
        b = mkf(line=20)
        out = aggregate([[a], [b]], dedup_window=15)
        self.assertEqual(len(out), 1)

    def test_dedup_contained_range(self):
        # A wide finding (1-100) and a narrow finding (50-60) on the same file/category
        # should merge — narrow range is fully contained in wide range.
        a = mkf(line=1, line_end=100)
        b = mkf(line=50, line_end=60)
        out = aggregate([[a], [b]])
        self.assertEqual(len(out), 1)

    def test_demote_picks_most_specific_glob(self):
        # Broad glob says "skip prose nits" but narrow glob has no suppression keyword.
        # The narrow (more specific) glob should win → finding stays at nit.
        f = mkf(file="docs/api/auth.md", category="prose", severity="nit")
        pi = [
            PathInstruction(path_glob="**/*", instructions="skip prose nits"),
            PathInstruction(path_glob="docs/api/*.md", instructions="be strict on API docs"),
        ]
        out = aggregate([[f]], path_instructions=pi)
        self.assertEqual(out[0].severity, "nit")


if __name__ == "__main__":
    unittest.main()
