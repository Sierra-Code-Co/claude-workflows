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
# Read this as an IDLE timeout, not a wall-clock one. `urllib`'s `timeout` is a
# per-socket-operation deadline: it fires when no bytes arrive for this long,
# and never fires at all while a long answer keeps streaming. Measured in the
# post-fix run — 5 calls ran 216-380s on a SINGLE attempt (retry_count=0) under
# this 180s value, emitting 17K-31K output tokens each. That is the intended
# outcome: a long streaming answer is a working review, not a hung call.
TIMEOUT_SEC = 180.0

# Ceiling on the RETRY SEQUENCE — not on a single attempt, which the paragraph
# above explains cannot be bounded this way. Without it, raising the per-attempt
# timeout multiplies by the attempt count: 3 x 180s is nine minutes on one
# doomed chunk, holding a worker slot throughout. What bounds a single
# pathological attempt is the run-level deadline in orchestrator.py, and since
# #27 hitting that is reported loudly rather than passing as a clean review.
MAX_CALL_SEC = 300.0


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
