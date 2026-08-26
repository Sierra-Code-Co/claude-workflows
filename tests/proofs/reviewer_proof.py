#!/usr/bin/env python3
"""Failure proof for the reviewer wave (T036, FR-007).

THE REGRESSION THIS GUARDS.

Setting `reasoning_effort=none` made every metric in the harness improve —
latency down, cost down, no errors — while the reviewers returned ZERO findings
on both planted-bug fixtures. Nothing failed. A faster, cheaper, completely blind
review is indistinguishable from a faster, cheaper, working one unless something
checks that a known bug is still found.

So this proof plants a bug the reviewer must find, and requires it to find MORE
in the planted diff than in the clean one.

WHY NOT "ZERO FINDINGS ON THE CLEAN DIFF".

Because that assertion is flaky against a live model and would be quietly
weakened the first time it failed, which is worse than not having it. The claim
that matters is DISCRIMINATION: a reviewer that reports on everything is as
useless as one that reports on nothing, and strictly-fewer catches both without
depending on the model being silent about clean code.

WHY THIS CANNOT BE REPLAYED FROM RECORDED RESPONSES.

Replaying fixed responses would prove the parser works and would have sailed
straight past `reasoning_effort=none` — the recorded responses still contain the
findings. The failure was in what the provider returned, so the call has to be
real. That makes this the one proof in the suite that needs a key and costs
money, which is why the UNPROVEN protocol below exists rather than a skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from review_plan_v2.providers import registry  # noqa: E402
from review_plan_v2.types import FileChange  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
PLANTED = FIXTURES / "03-sql-injection.diff"
CLEAN = FIXTURES / "01-clean.diff"

# Exit 3 is the suite's UNPROVEN signal: the gate was neither shown to fail nor
# shown to work. run-all.sh treats it as a failure unless the proof is named in
# RPV2_UNPROVEN_OK, so "we could not run it" can never quietly read as "it
# passed" — and the acknowledgement has to name THIS proof, so it cannot blanket
# a future one.
EXIT_UNPROVEN = 3


def _change(path: str, diff_text: str, language: str | None) -> FileChange:
    return FileChange(
        path=path,
        is_binary=False,
        is_renamed_from=None,
        added_lines=((1, 10_000),),
        diff_text=diff_text,
        language=language,
    )


def main() -> int:
    # The key the reviewer WILL use, asked of the registry.
    #
    # This read `os.environ.get("DEEPSEEK_API_KEY")`, hardcoded, and that stopped
    # being the right question when DeepSeek was removed from the tool: nothing
    # reads that variable any more, and `security.make()` below resolves its
    # provider from `registry.DEFAULT_BROAD`. So the gate asked for a key that
    # cannot enable anything and returned UNPROVEN on a machine where the real
    # key was present and the call would have succeeded — permanently
    # unpassable, and reporting the one wave that needs a live call as unproven
    # is how a blind-reviewer regression gets through. Exactly the fail-silent
    # shape the rest of this branch is about, so it is fixed here rather than
    # left for the provider it names to be noticed as dead.
    #
    # Derived, not restated: `make()` takes the default from the registry for the
    # documented reason that four copies of a literal default is how the DeepSeek
    # one outlived the decision to drop it. A second copy here would recreate that.
    tag = registry.DEFAULT_BROAD
    if not registry.has_key(tag):
        print(
            f"UNPROVEN: the reviewer wave was not exercised — no API key for the "
            f"default\n"
            f"          broad provider: {registry.missing_key_hint(tag)}.\n"
            "          This gate cannot be proven offline: replaying recorded "
            "responses would\n"
            "          have sailed straight past the reasoning_effort=none "
            "regression, because\n"
            "          the recorded responses still contain the findings. The "
            "call has to be real."
        )
        return EXIT_UNPROVEN

    for path in (PLANTED, CLEAN):
        if not path.is_file():
            print(f"FAIL: fixture missing: {path}")
            return 1

    from review_plan_v2.reviewers import security

    reviewer = security.make()

    # A provider error is UNPROVEN, not FAIL, and neither is a traceback.
    #
    # The three outcomes are genuinely different and CI has to tell them apart:
    # the reviewers went blind (FAIL — the regression this guards), the call
    # never completed (UNPROVEN — rate limit, network, revoked key), or it
    # worked. Letting an exception escape collapses the middle case into a
    # crash, and a crashing proof gets muted long before anyone diagnoses it.
    #
    # A BUG IN THIS FILE IS NOT AN UNPROVEN CALL, and `except Exception` could not
    # tell them apart. A NameError or a TypeError in the two lines below — a rename
    # not carried through, a signature that moved — printed "the reviewer call did
    # not complete" and returned UNPROVEN, which reads as "rate limit, try later"
    # and gets muted. The proof would then be permanently unpassable for a reason
    # that has nothing to do with the regression it guards, which is exactly how
    # its DEEPSEEK_API_KEY gate stayed dead. Programming errors re-raise and crash
    # loudly; only the failures the UNPROVEN verdict is ABOUT are swallowed.
    # Read the fixtures BEFORE the try, so a missing or unreadable fixture cannot
    # be reported as a provider failure. Both reads used to sit inside it, and a
    # FileNotFoundError from a moved fixture landed in `except Exception` and
    # printed "the reviewer call did not complete" — no call had been made at all.
    # That reads as "rate limit, try later" and gets muted, which is the same way
    # this proof's DEEPSEEK_API_KEY gate stayed dead, and it is what the paragraph
    # above means by A BUG IN THIS FILE IS NOT AN UNPROVEN CALL.
    #
    # Two reviewers proposed adding OSError to the re-raise tuple instead. Do not:
    # urllib.error.URLError SUBCLASSES OSError, so every genuine network failure —
    # the exact case the UNPROVEN verdict exists for — would re-raise and crash the
    # proof. Hoisting the reads out is what separates the two without widening the
    # tuple; nothing left in the try is anything but the call.
    planted_src = PLANTED.read_text()
    clean_src = CLEAN.read_text()
    try:
        planted = reviewer.run(_change("web/src/lib/server/db.ts", planted_src, "ts"))
        clean = reviewer.run(_change("web/src/lib/server/ok.ts", clean_src, "ts"))
    except (NameError, TypeError, AttributeError, ImportError, IndexError, KeyError):
        raise
    except Exception as exc:
        print(
            f"UNPROVEN: the reviewer call did not complete, so the wave was "
            f"neither shown to fail nor shown to work: "
            f"{type(exc).__name__}: {exc}"
        )
        return EXIT_UNPROVEN

    if not planted:
        print(
            "FAIL: the reviewer returned ZERO findings on the planted-bug "
            "fixture.\n"
            "      This is the exact state reasoning_effort=none produced, and "
            "every other\n"
            "      metric looked better while it held."
        )
        return 1

    if len(clean) >= len(planted):
        print(
            f"FAIL: no discrimination — {len(clean)} finding(s) on the clean "
            f"fixture vs {len(planted)} on the planted-bug one. A reviewer that "
            f"reports on everything is as useless as one that reports on nothing."
        )
        return 1

    # The finding has to be about the PLANTED bug, not merely present.
    #
    # "found something on the buggy diff and nothing on the clean one" is
    # satisfied by a reviewer that emits one generic nit about the dirty file
    # and happens to like the clean one — which passes while being exactly as
    # blind as reasoning_effort=none was. The count proves discrimination; only
    # the content proves the right thing was discriminated.
    #
    # Matched on topic keywords rather than exact text because the wording is a
    # live model's. Keep this list wide enough to survive rephrasing and narrow
    # enough that an unrelated style nit cannot satisfy it.
    topic = ("sql", "injection", "parameteri", "sanitiz", "sanitis", "escap")
    hits = [
        f for f in planted
        if any(k in f"{getattr(f, 'message', '')} {getattr(f, 'category', '')}".lower()
               for k in topic)
    ]
    if not hits:
        print(
            f"FAIL: {len(planted)} finding(s) on the planted diff, but none of "
            f"them is about the seeded SQL injection: "
            f"{[getattr(f, 'message', str(f))[:90] for f in planted][:3]}\n"
            f"      A generic nit on the buggy file is not evidence the reviewer "
            f"still finds the planted bug."
        )
        return 1

    print(
        f"ok: reviewer wave found {len(planted)} finding(s) on the planted bug "
        f"({len(hits)} naming the injection) and {len(clean)} on clean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
