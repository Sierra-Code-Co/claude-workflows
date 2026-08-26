"""Shared call-budget defaults for every provider.

These live in one module on purpose. Each provider previously carried its own
`TIMEOUT_SEC = 30.0` copy-pasted from the one before it, so a value that was
wrong was wrong in three places at once and fixing one left the others silently
broken. That is the same shape as the telemetry `timestamp` field, which was in
the allow-list from day one but never written because every provider had to
remember to send it — 30,956 records with no time axis.

Why these numbers (all measured 2026-08-13 against one real reviewer diff):

  max_tokens is a COMBINED reasoning+answer budget on every current reasoning
  model — DeepSeek v4-pro/v4-flash, Gemini 3.1 Pro, GPT-5.x alike. Reasoning is
  generated first, so a hard chunk spends the whole allowance thinking and
  returns HTTP 200 with an empty answer. At the previous 8192:

      security      10.6s   reasoning   738   -> answer OK
      tests         64.9s   reasoning 7,249   -> answer OK, 95% of budget
      correctness   78.4s   reasoning 8,192   -> EMPTY (capped)
      consistency   73.4s   reasoning 8,192   -> EMPTY (capped)

  Half the reviewers returned nothing, and the failure rate tracked the
  difficulty of the analysis rather than anything about the network:
  correctness failed 10.2% of production calls, security 0.77%. The same chunk
  answered at 32768 using 22,512 reasoning tokens.

  Raising this does NOT raise average cost. Billing is per token generated and
  the median successful call emits 334 (n=26,682); this lifts only the ceiling,
  and it is spent precisely where the review is hard.

  Do NOT reach for a reasoning-suppression parameter instead. Measured on the
  repo's own planted-bug fixtures, `reasoning_effort=none` returned 0 findings
  on both 02-pascalcase-bug and 03-sql-injection, which the default finds
  correctly in under 20s. `low` is accepted and silently ignored (so is a
  deliberate nonsense field), leaving behaviour identical to sending nothing.
"""
from __future__ import annotations

import math
import os

# Measured at the NEW limit, not under the old one.
#
# 32768 was sized from a run where 22,512 reasoning tokens was the largest
# figure anyone had seen — and that number came from a distribution censored at
# 32768, so it could not describe its own tail. It then failed exactly as the
# censoring predicted: on 2026-08-15 the correctness reviewer returned empty on
# the two largest files of a real diff, `reasoning_tokens=32768, budget=32768`,
# twice in a row, and the resulting reviews were INCOMPLETE on precisely the
# files most worth reviewing.
#
# Re-measured with the ceiling raised, which is the only way to see past a
# cutoff (n=80 calls, same diff, same models):
#
#     budget    failed   max completion_tokens observed
#     32768     2/80     31,824  (97.1% of budget -> the two empty answers)
#     65536     0/80     64,006  (97.7% of budget -> answered)
#
# So 65536 clears this diff and NOT by much: the worst call finished 1,530
# tokens under the ceiling. It is also the largest value the DeepSeek API
# accepts, so there is no further headroom to buy — which is why the
# near-exhaustion warning below matters more than the constant does.
#
# Cost is unaffected on average. Billing is per token GENERATED and the median
# successful call emits 334 (n=26,682); this lifts only the ceiling, spent
# precisely where the review is hard. What it does buy is latency: the hardest
# calls in the 65536 run ran to 1,011s. That is not bounded by TIMEOUT_SEC (an
# idle timeout — a streaming answer never trips it) nor by MAX_CALL_SEC (which
# bounds the retry SEQUENCE, checked between attempts). A single hard call is
# bounded only by the run-level deadline in orchestrator.py, and since #27
# hitting that is reported loudly rather than passing as a clean review.
MAX_TOKENS = 65536

# A successful call this close to the ceiling is the LAST warning you get.
#
# The failure mode is binary and silent: at 97.1% of budget the answer arrives,
# at 100% it is empty and the reviewer reports nothing. Nothing in between warns
# you, so the first sign of an undersized budget has always been a review that
# quietly covered less than it claimed. This threshold turns the tail into a
# signal BEFORE it becomes an empty answer.
NEAR_BUDGET_RATIO = 0.90


def max_tokens() -> int:
    """The per-call combined reasoning+answer budget, overridable per run.

    An override exists because the right value is diff-dependent and the wrong
    value fails silently — and because sizing it correctly requires measuring AT
    or ABOVE the current limit, which is impossible if changing it needs a code
    edit and a release.
    """
    return env_int("REVIEW_PLAN_V2_MAX_TOKENS", MAX_TOKENS)

# Easy chunks answer in 10-19s, reasoning-heavy ones in 65-125s. The old 30s
# wall killed every hard call and, because budget exhaustion takes 78-124s to
# come back, reported it as a transient network fault.
#
# This is a WALL-CLOCK cap on total generation time, not an idle timeout.
#
# It was documented as an idle timeout until 2026-08-25, on the reasoning that
# `urllib`'s `timeout` is a per-socket-operation deadline and so "never fires at
# all while a long answer keeps streaming". The premise is true and the
# conclusion does not follow, because neither live provider streams: google.py
# posts to `:generateContent` (not `:streamGenerateContent`) and openai.py sends
# `"stream": False`. One response arrives in one piece, so "no bytes for
# TIMEOUT_SEC" means "the model has not finished in TIMEOUT_SEC", and this value
# is a hard cap on how long a review is allowed to think.
#
# The old comment cited 5 calls running 216-380s on a single attempt "under this
# 180s value" as evidence of the streaming behaviour. Against a non-streaming
# endpoint that cannot happen, and the telemetry agrees: across 1,668 logged
# calls (~/.claude/review-plan-v2/logs/calls.jsonl) the largest SUCCESSFUL
# latency under the 180s value was 179.6s and not one call exceeded 180.0s,
# while 10 calls died at 180.1-180.4s. A distribution whose maximum sits 0.4s
# under the configured ceiling is being clipped by it, not passing through it.
#
# Sized by measuring ABOVE the old ceiling, which is the only way to see past a
# cutoff and the same method the max_tokens note above describes. Re-running the
# two exact reviewer x file pairs that died, with the ceiling raised via
# REVIEW_PLAN_V2_GOOGLE_TIMEOUT=900:
#
#     security     scripts/review-plan-v2.sh                      211.2s  -> OK, 1 finding
#     correctness  tests/unit/test_request_prompt_extraction.py    134.7s  -> OK, 0 findings
#
# So the 180s wall was killing work that finishes and returns findings. 420
# covers the worst figure this file has ever recorded from any run (380s) with
# headroom, and the honest caveat is the one the max_tokens note makes about
# itself: n is small (2 calls), so the tail above 211s is measured on nothing
# and 420 is chosen for margin rather than derived from data. The asymmetry
# justifies erring high — a too-high value costs extra wall clock only on calls
# that are genuinely stuck, while a too-low one discards a completed review and,
# per the arithmetic below, does not even retry it.
TIMEOUT_SEC = 420.0

# Shared so the retry policy has ONE definition. Each provider carried its own
# `RETRY_SLEEPS = (1.0, 4.0)`, which is the same copy-paste this module exists to
# end — and worse here than for a timeout, because MAX_CALL_SEC below is derived
# from it: a provider that lengthened its local copy would silently buy itself
# fewer retries, not more.
RETRY_SLEEPS = (1.0, 4.0)

# Room for TLS setup, DNS, and the log/parse work bracketing each attempt, so the
# derivation below is not defeated by a fraction of a second.
RETRY_BUDGET_SLACK_SEC = 15.0


def derive_max_call_sec(timeout: float = TIMEOUT_SEC,
                        sleeps: tuple[float, ...] = RETRY_SLEEPS,
                        slack: float = RETRY_BUDGET_SLACK_SEC) -> float:
    """Ceiling on the RETRY SEQUENCE, sized to afford exactly one retry.

    DERIVED rather than chosen, because the standalone 300.0 it replaces made the
    retry logic unreachable. The providers' guard refuses any attempt that could
    overrun this budget — `elapsed + sleep_for + timeout > max_call_sec` — so
    after a full-length stall the arithmetic was 180 + 1 + 180 = 361 > 300, and
    every timed-out call gave up with zero retries. All 10 timeout kills in the
    telemetry log `retry_count: 0`. Two retries were configured, none could ever
    run, and nothing said so: the run reported a transient provider fault.

    That is the failure this module was written about, one level up. A hand-set
    constant next to the value it has to accommodate drifts from it, and the
    resulting dead code reports someone else's fault.

    The shape is `2 * timeout` so that a first attempt which burns the entire
    per-attempt wall can still be followed by one full-length retry, plus the
    first sleep, plus slack. A THIRD attempt needs 3 * timeout and is refused,
    which is the intended ceiling: one retry is worth a stalled provider, three
    is 21 minutes on one doomed chunk while holding a worker slot.

    The slack is CAPPED at half the headroom to that refusal boundary, and the cap
    is the whole reason this is not `+ slack` outright. A fixed 15s addition is
    negligible beside a 420s timeout and decisive beside a 10s one: measured over a
    timeout sweep, `timeout < 12` bought a third attempt while this docstring said
    a third attempt was refused. Which is this module's own headline defect a third
    time — a derivation that holds for the shipped constants and not for the
    overrides — so the ceiling now brackets itself:

        allow one retry:  max >= 2 * timeout + sleeps[0]              (lower bound)
        refuse a third:   max <  3 * timeout + sleeps[0] + sleeps[1]  (upper bound)

    The headroom between those is `timeout + sleeps[1]`, always positive, and half
    of it is therefore always strictly inside the bracket. At the shipped values the
    cap does not bind (min(15, 212) = 15, ceiling 856 unchanged), so this narrows no
    behaviour anyone has run; it removes a range where the contract was false.
    """
    first_sleep = sleeps[0] if sleeps else 0.0
    second_sleep = sleeps[1] if len(sleeps) > 1 else 0.0
    headroom = timeout + second_sleep
    return 2.0 * timeout + first_sleep + min(slack, headroom / 2.0)


MAX_CALL_SEC = derive_max_call_sec()


def resolve_call_budget(timeout_var: str, max_call_var: str,
                        timeout: float | None = None) -> tuple[float, float]:
    """Resolve (timeout, max_call_sec) so an override cannot break the retry rule.

    The constants above are derived from each other. The ENV OVERRIDES were not,
    and that reintroduced the exact defect this module was written to end — one
    level out, where the derivation could not see it. Each provider read:

        timeout      = env_float("..._TIMEOUT",  TIMEOUT_SEC)
        max_call_sec = env_float("..._MAX_CALL", MAX_CALL_SEC)   # import-time
        timeout      = min(timeout, max_call_sec)

    so raising only the timeout left the ceiling at its default and the clamp
    then quietly cut the timeout back down to it. Measured, at the shipped
    values (TIMEOUT_SEC=420, MAX_CALL_SEC=856):

        REVIEW_PLAN_V2_GOOGLE_TIMEOUT=900 -> max_call_sec stays 856, timeout
            silently clamped 900 -> 856, attempts = 1.  ZERO retries, which is
            the original bug verbatim.
        REVIEW_PLAN_V2_GOOGLE_TIMEOUT=180 -> attempts = 3, a third attempt the
            derivation deliberately refuses (see derive_max_call_sec).

    Both directions are silent: nothing prints, and the failure surfaces as a
    `transient` provider fault — someone else's fault, again. It is not a corner
    case either. `..._TIMEOUT=900` is the documented way to measure latency above
    the ceiling, and is how TIMEOUT_SEC itself was sized, so the one workflow the
    override exists for is the one that disabled retries.

    So the ceiling is DERIVED from the timeout in force unless an operator sets
    it explicitly. Junk in the max-call var derives too, rather than falling back
    to the stale import-time constant: a typo must not silently restore the bug.
    """
    if timeout is None:
        timeout = env_float(timeout_var, TIMEOUT_SEC)
    # 0.0 as the default is the "unset" signal — env_float already rejects
    # non-positive and non-finite input, so junk and absent land in one branch.
    explicit = env_float(max_call_var, 0.0)
    max_call_sec = explicit if explicit else derive_max_call_sec(timeout)
    # Still clamped, for the one case the derivation cannot fix: an operator who
    # sets the ceiling explicitly BELOW the timeout means the ceiling.
    return min(timeout, max_call_sec), max_call_sec


def affordable_attempts(timeout: float = TIMEOUT_SEC,
                        max_call_sec: float | None = None,
                        sleeps: tuple[float, ...] = RETRY_SLEEPS) -> int:
    """How many attempts the budget can pay for if every one stalls full length.

    Replays the providers' own guard rather than restating its result, so a test
    can assert the retry count the configuration actually buys. Asserting on the
    constants instead would just re-check arithmetic; this re-checks the rule.

    `max_call_sec` DERIVES from the supplied timeout when omitted, rather than
    defaulting to the import-time MAX_CALL_SEC. With the constant as the default,
    `affordable_attempts(timeout=900)` reported the retry budget of a
    configuration nobody was running — the answer for a 900s timeout under an
    856s ceiling derived from 420 — so the helper written to prove the retry rule
    would have confirmed the override bug above instead of catching it.
    """
    if max_call_sec is None:
        max_call_sec = derive_max_call_sec(timeout, sleeps)
    elapsed = 0.0
    attempts = 1                      # attempt 0 is never budget-checked
    for sleep_for in sleeps:
        elapsed += timeout            # the attempt before this one stalled out
        if elapsed + sleep_for + timeout > max_call_sec:
            break
        elapsed += sleep_for
        attempts += 1
    return attempts


def env_float(name: str, default: float) -> float:
    """Read a positive float override; ignore junk rather than crash the run.

    A typo'd override must fall back to the default, never to 0 — a zero timeout
    would disable the wall entirely and read as "no failures". `inf` is the same
    hazard wearing a positive sign: `float("inf") > 0` is True, so an unguarded
    positivity check accepts it and removes the ceiling outright. (`nan` fails
    every comparison and so falls back on its own, but rely on isfinite rather
    than on that accident.)
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 and math.isfinite(val) else default


def env_int(name: str, default: int) -> int:
    """Read a positive int override; ignore junk rather than crash the run.

    Same contract as `env_float`, and the same hazard: a typo'd budget must fall
    back to the default rather than to 0, because a zero budget returns an empty
    answer on EVERY call — which this codebase renders as "reviewed, found
    nothing". `float("inf")` and `nan` are rejected via the shared helper before
    the int conversion, so `REVIEW_PLAN_V2_MAX_TOKENS=inf` cannot remove the
    ceiling outright.
    """
    val = env_float(name, float(default))
    return int(val) if val >= 1 else default


def budget_fields(completion_tokens: int, budget: int, reviewer: str,
                  stream=None) -> dict[str, object]:
    """Warn if a SUCCESSFUL call came close to the ceiling, and return the
    telemetry fields recording it.

    Shared rather than written per provider, because it was written for DeepSeek
    first and ruff caught the constant sitting unused in the other two — the
    same shape as the `TIMEOUT_SEC = 30.0` that was copy-pasted into three
    providers and therefore wrong in three places at once. Budget exhaustion is
    not a DeepSeek quirk: it is how every current reasoning model behaves when
    reasoning and answer share one allowance.
    """
    import sys as _sys
    stream = stream if stream is not None else _sys.stderr
    near = bool(budget) and completion_tokens >= NEAR_BUDGET_RATIO * budget
    if near:
        print(
            f"WARNING: reviewer {reviewer} used {completion_tokens} of {budget} "
            f"budget tokens ({completion_tokens / budget:.0%}) and still "
            f"answered. A slightly harder chunk returns an EMPTY answer, which "
            f"reads as 'found nothing'. Raise REVIEW_PLAN_V2_MAX_TOKENS.",
            file=stream,
        )
    return {"max_tokens": budget, "near_budget": near}
