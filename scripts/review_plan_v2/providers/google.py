"""Google Gemini provider client. Different shape from chat-completions:

Endpoint: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=API_KEY
Body:     { "system_instruction": { "parts": [{"text": "..."}] },
            "contents": [{"role": "user", "parts": [{"text": "..."}]}],
            "generationConfig": { "maxOutputTokens": ... } }
Response: { "candidates": [{"content": {"parts": [{"text": "..."}]}}],
            "usageMetadata": {"promptTokenCount": ..., "candidatesTokenCount": ...} }

Used as a cascade reviewer alongside openai.py for high-risk paths (anti-self-grading
on Claude-written code).

Default model: gemini-2.5-pro. Override via REVIEW_PLAN_V2_GOOGLE_MODEL env.
API key from GEMINI_API_KEY (matches the companion-ai eval harness convention).
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..telemetry import log_call
from ..types import CallResult
from ._budget import (
    RETRY_SLEEPS,
    budget_fields,
    resolve_call_budget,
)
from ._budget import max_tokens as resolve_max_tokens
from ._errors import is_blank, redact, summarize_error_body

DEFAULT_BASE = "https://generativelanguage.googleapis.com"
# gemini-2.5-pro still resolves, but 3.1-pro is the current frontier tier.
# Tradeoff recorded deliberately: measured 51.2s vs 15.7s for 2.5-pro on the
# same reviewer-shaped hunk, and it is a `-preview` id. Acceptable because
# the Google leg is CASCADE-only (high-risk paths, a small file subset) and
# the wall-clock budget now scales with queued work. Override per-run with
# REVIEW_PLAN_V2_GOOGLE_MODEL if the latency bites.
DEFAULT_MODEL = "gemini-3.1-pro-preview"
# RETRY_SLEEPS is imported from _budget, not defined here: MAX_CALL_SEC is derived
# from it, so a local copy would silently change how many retries this provider
# can afford without changing the budget that pays for them.
ALLOWED_SCHEMES = ("http", "https")


def _validated_base(raw: str) -> str:
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        return DEFAULT_BASE
    return raw.rstrip("/")


def _classify(status: int | None, exc: Exception | None) -> tuple[str | None, bool]:
    if exc is not None:
        if isinstance(exc, TimeoutError):
            return "transient", True
        if isinstance(exc, urllib.error.URLError):
            return "transient", True
        # A dropped or reset connection is the textbook retryable fault, and
        # neither shape subclasses URLError, so both fell through to
        # non-retryable "unknown" and killed the whole reviewer task.
        #
        # This exact fix was made in deepseek.py — the one provider that can no
        # longer run — and never ported to the two that can. The 2026-08-25
        # pre-push run on this branch lost 1 of 394 reviewer tasks to
        # `unknown (HTTP no-response) — Remote end closed connection without
        # response` and reported the whole review INCOMPLETE with exit 2, on one
        # dropped socket out of 394 that a single retry would have covered. It
        # also explains the shape of the 8 `unknown` kills at 180.1-180.4s in the
        # telemetry log that I could not reproduce: a server-side disconnect,
        # classified as a hard fault, retried never.
        #
        # HTTPException as well as ConnectionError: RemoteDisconnected inherits
        # from BOTH (ConnectionResetError and BadStatusLine), but IncompleteRead
        # is HTTPException only, so ConnectionError alone would miss a truncated
        # response body.
        if isinstance(exc, (ConnectionError, http.client.HTTPException)):
            return "transient", True
        return "unknown", False
    if status is None:
        return "unknown", False
    if status in (401, 403):
        return "auth", False
    if status == 429:
        return "rate_limit", True
    if 500 <= status < 600:
        return "transient", True
    if 200 <= status < 300:
        return None, False
    return "unknown", False


def _post_once(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(system_prompt: str, user_prompt: str, model: str | None = None,
         max_tokens: int | None = None, timeout: float | None = None,
         reviewer: str = "unknown") -> CallResult:
    """Call Google Gemini's generateContent endpoint. Returns CallResult."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return CallResult(content=None, error_kind="auth", retryable=False, status_code=None)

    if max_tokens is None:
        # Resolved HERE, not as a default argument: a default is evaluated at
        # import time, so REVIEW_PLAN_V2_MAX_TOKENS set by a wrapper or a test
        # would be read before the override existed and silently ignored.
        max_tokens = resolve_max_tokens()

    # Resolved together, not one env var each. Reading them independently left the
    # ceiling at its import-time value when only the timeout was overridden, and
    # the clamp then cut the timeout back to it — buying zero retries at
    # REVIEW_PLAN_V2_GOOGLE_TIMEOUT=900 and three attempts at 180. See
    # _budget.resolve_call_budget for the measured numbers.
    timeout, max_call_sec = resolve_call_budget(
        "REVIEW_PLAN_V2_GOOGLE_TIMEOUT", "REVIEW_PLAN_V2_GOOGLE_MAX_CALL", timeout)

    if model is None:
        model = os.environ.get("REVIEW_PLAN_V2_GOOGLE_MODEL", DEFAULT_MODEL)

    base = _validated_base(os.environ.get("GOOGLE_API_BASE", DEFAULT_BASE))
    # Gemini uses ?key=API_KEY in the query string. URL-encode in case.
    url = f"{base}/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    test_fix = os.environ.get("REVIEW_PLAN_V2_TEST_FIXTURE")
    if test_fix:
        headers["X-Test-Fixture"] = test_fix
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }

    last_err_kind = "unknown"
    last_status: int | None = None
    last_detail: str | None = None
    started = time.monotonic()
    retry_count = 0

    for attempt in range(1 + len(RETRY_SLEEPS)):
        if attempt > 0:
            # Never start an attempt the call budget cannot pay for. A retry
            # about to be cut off mid-flight buys nothing and holds a worker
            # slot for the whole doomed attempt.
            elapsed = time.monotonic() - started
            sleep_for = RETRY_SLEEPS[attempt - 1]
            if elapsed + sleep_for + timeout > max_call_sec:
                last_err_kind = last_err_kind or "transient"
                last_detail = (
                    f"{last_detail or 'attempt failed'} \u2014 gave up after "
                    f"{elapsed:.0f}s; a further attempt would exceed the "
                    f"{max_call_sec:.0f}s per-call budget"
                )
                break
            time.sleep(RETRY_SLEEPS[attempt - 1])
            retry_count += 1
        try:
            status, raw = _post_once(url, headers, payload, timeout)
            last_status = status
            kind, retryable = _classify(status, None)
            if kind is None:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                    candidates = parsed.get("candidates") or []
                    if not candidates:
                        last_err_kind = "empty"
                        # promptFeedback carries the block reason when Gemini
                        # refuses outright and returns no candidate at all.
                        feedback = parsed.get("promptFeedback") or {}
                        last_detail = (
                            "HTTP 200 but no candidates (blockReason="
                            f"{feedback.get('blockReason') or 'unspecified'})"
                        )
                        break
                    parts = (candidates[0].get("content") or {}).get("parts") or []
                    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
                    content = "".join(text_parts)
                    if is_blank(content):
                        # Was classified "parse", which reads like a bug in our
                        # decoder. It is not — the provider answered and said
                        # nothing, and finishReason (MAX_TOKENS / SAFETY / ...)
                        # is the one field that distinguishes the causes.
                        last_err_kind = "empty"
                        last_detail = (
                            "HTTP 200 but empty content (finishReason="
                            f"{candidates[0].get('finishReason') or 'unknown'}, "
                            f"budget={max_tokens})"
                        )
                        break
                    usage = parsed.get("usageMetadata") or {}
                    log_call({
                        "provider": "google", "model": model, "reviewer": reviewer,
                        "input_tokens": int(usage.get("promptTokenCount", 0)),
                        "output_tokens": int(usage.get("candidatesTokenCount", 0)),
                        **budget_fields(int(usage.get("candidatesTokenCount", 0)), max_tokens, reviewer),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "timeout_sec": timeout, "max_call_sec": max_call_sec,
                        "status_code": status, "error_kind": None, "retry_count": retry_count,
                    })
                    return CallResult(
                        content=content, error_kind=None, retryable=False,
                        status_code=status,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        input_tokens=int(usage.get("promptTokenCount", 0)),
                        output_tokens=int(usage.get("candidatesTokenCount", 0)),
                    )
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    last_err_kind = "parse"
                    last_detail = f"could not parse a 2xx response body: {type(e).__name__}"
                    break
            last_err_kind = kind
            # This leg's 23 × HTTP 404 burst was a stale model id. The body says
            # so outright ("models/... is not found"), and summarize_error_body
            # redacts before returning — mandatory here, because this provider
            # passes its API key as a URL query parameter, so any echoed request
            # context is a live credential.
            last_detail = summarize_error_body(raw)
            if not retryable:
                break
        # http.client.HTTPException is in the tuple because IncompleteRead — a
        # response body that stops mid-stream — is HTTPException and NOT OSError,
        # so it escaped this handler entirely and propagated out of call() as an
        # uncaught exception. Classifying it as retryable without catching it here
        # would have been a fix that does nothing, which is the shape of half the
        # defects on this branch. RemoteDisconnected was already caught (it is a
        # ConnectionResetError as well), just classified wrong.
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as e:
            last_err_kind, retryable = _classify(None, e)
            last_detail = redact(str(e) or type(e).__name__)
            if not retryable:
                break

    # The failure row carries the budgets too. It did not, and the ONE class of row
    # where the ceiling is the likely cause was the class that recorded no ceiling.
    #
    # `max_tokens` by hand rather than `**budget_fields(0, max_tokens, reviewer)`,
    # deliberately. Four review gates have asked for the helper here, on the
    # reasonable-looking grounds that the success row uses it and the two rows
    # should share a schema. The helper's other field is `near_budget`, and on a
    # failure it is not merely False but UNKNOWABLE: completion_tokens is 0 because
    # the call produced nothing, not because it used nothing. A call killed at the
    # wall may well have been about to overrun its token budget, so writing
    # `near_budget: false` onto a failure row would be a checkable-looking claim
    # that was never checked — the defect this branch is almost entirely about,
    # committed in the name of schema tidiness. The asymmetry is the honest record,
    # and tests/unit/test_failure_row_schema.py asserts it rather than leaving the
    # next reviewer to ask a fifth time.
    log_call({
        "provider": "google", "model": model, "reviewer": reviewer,
        "input_tokens": 0, "output_tokens": 0, "max_tokens": max_tokens,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "timeout_sec": timeout, "max_call_sec": max_call_sec,
        "status_code": last_status, "error_kind": last_err_kind, "retry_count": retry_count,
    })
    return CallResult(
        content=None, error_kind=last_err_kind, retryable=False,
        error_detail=last_detail,
        status_code=last_status,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
