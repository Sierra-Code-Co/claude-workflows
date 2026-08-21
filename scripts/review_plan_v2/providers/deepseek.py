"""DeepSeek provider client. urllib-based, with timeout + bounded retry."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..telemetry import log_call
from ..types import CallResult
from ._budget import MAX_CALL_SEC, TIMEOUT_SEC, budget_fields, env_float, max_tokens as resolve_max_tokens
from ._errors import is_blank, redact, summarize_error_body


DEFAULT_BASE = "https://api.deepseek.com"
# `deepseek-reasoner` is now only an ALIAS and silently resolves to the
# cheapest tier: sending it returns `"model":"deepseek-v4-flash"` in the
# response body (verified live 2026-08-01). The broad-pass reviewer was
# therefore running the weakest model in the family while the skill doc
# still advertised an R1 reasoning pass. `deepseek-r1` now 400s outright:
# "The supported API model names are deepseek-v4-pro or deepseek-v4-flash".
# Pin the pro tier explicitly. Measured 19.3s on a reviewer-shaped hunk.
DEFAULT_MODEL = "deepseek-v4-pro"




RETRY_SLEEPS = (1.0, 4.0)  # 2 retries on transient/rate_limit
ALLOWED_SCHEMES = ("http", "https")



def _validated_base(raw: str) -> str:
    """Reject base URLs with non-HTTP schemes (basic SSRF guard if env is poisoned)."""
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
        if isinstance(exc, ConnectionError):
            # ConnectionResetError does NOT subclass URLError, so it fell through
            # to non-retryable "unknown". Long reviewer responses are exactly
            # when a peer reset happens (hit live while probing a 300s call), and
            # it is the textbook retryable fault.
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
        return None, False  # type: ignore[return-value]
    return "unknown", False


def _post_once(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL,
         max_tokens: int | None = None, timeout: float | None = None,
         reviewer: str = "unknown") -> CallResult:
    """Call DeepSeek's Chat Completions endpoint. Returns CallResult.

    Strips reasoning_content; returns only the final answer in `content`.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return CallResult(content=None, error_kind="auth", retryable=False, status_code=None)

    if max_tokens is None:
        # Resolved HERE, not as a default argument: a default is evaluated at
        # import time, so REVIEW_PLAN_V2_MAX_TOKENS set by a wrapper or a test
        # would be read before the override existed and silently ignored.
        max_tokens = resolve_max_tokens()

    if timeout is None:
        timeout = env_float("REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT", TIMEOUT_SEC)
    max_call_sec = env_float("REVIEW_PLAN_V2_DEEPSEEK_MAX_CALL", MAX_CALL_SEC)
    # A budget checked only before retries is not a budget: with
    # REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT above MAX_CALL, attempt 0 alone overruns it.
    timeout = min(timeout, max_call_sec)

    base = _validated_base(os.environ.get("DEEPSEEK_API_BASE", DEFAULT_BASE))
    url = f"{base}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    test_fix = os.environ.get("REVIEW_PLAN_V2_TEST_FIXTURE")
    if test_fix:
        headers["X-Test-Fixture"] = test_fix
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    last_err_kind = "unknown"
    last_status: int | None = None
    last_detail: str | None = None
    started = time.monotonic()
    retry_count = 0
    content: str | None = None

    for attempt in range(1 + len(RETRY_SLEEPS)):
        if attempt > 0:
            # Never start an attempt the call budget cannot pay for. A retry
            # that is going to be cut off mid-flight buys nothing and holds a
            # worker slot for the whole doomed attempt.
            elapsed = time.monotonic() - started
            sleep_for = RETRY_SLEEPS[attempt - 1]
            if elapsed + sleep_for + timeout > max_call_sec:
                last_err_kind = last_err_kind or "transient"
                last_detail = (
                    f"{last_detail or 'attempt failed'} — gave up after "
                    f"{elapsed:.0f}s; a further attempt would exceed the "
                    f"{max_call_sec:.0f}s per-call budget"
                )
                break
            time.sleep(sleep_for)
            retry_count += 1
        try:
            status, raw = _post_once(url, headers, payload, timeout)
            last_status = status
            kind, retryable = _classify(status, None)
            if kind is None:
                # Success
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                    choice = (parsed.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    content = msg.get("content")
                    if is_blank(content):
                        # Name the actual cause. `max_tokens` is a COMBINED
                        # reasoning+answer budget on v4-pro/v4-flash: the model
                        # generates reasoning first, and a hard chunk spends the
                        # whole allowance on it, leaving nothing for the answer.
                        # Measured 2026-08-13 on a concurrency diff:
                        # reasoning_tokens=8192 of budget=8192, content "",
                        # reasoning_content 35,185 chars — after 104 seconds.
                        # Without these two numbers in the message this reads as
                        # a generic provider hiccup, which is how it survived.
                        u = parsed.get("usage") or {}
                        reasoning = (u.get("completion_tokens_details") or {}).get(
                            "reasoning_tokens", 0
                        )
                        finish = choice.get("finish_reason") or "unknown"
                        last_err_kind = "empty"
                        last_detail = (
                            f"HTTP 200 but empty content (finish_reason={finish}, "
                            f"reasoning_tokens={reasoning}, budget={max_tokens}). "
                            "reasoning_tokens at budget means the model spent the "
                            "whole allowance thinking; raise max_tokens."
                        )
                        break
                    usage = parsed.get("usage") or {}
                    completion = int(usage.get("completion_tokens", 0))

                    log_call({
                        "provider": "deepseek", "model": model, "reviewer": reviewer,
                        "input_tokens": int(usage.get("prompt_tokens", 0)),
                        "output_tokens": completion,
                        **budget_fields(completion, max_tokens, reviewer),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "status_code": status, "error_kind": None, "retry_count": retry_count,
                    })
                    return CallResult(
                        content=content, error_kind=None, retryable=False,
                        status_code=status,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        input_tokens=int(usage.get("prompt_tokens", 0)),
                        output_tokens=int(usage.get("completion_tokens", 0)),
                    )
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    last_err_kind = "parse"
                    last_detail = f"could not parse a 2xx response body: {type(e).__name__}"
                    break
            last_err_kind = kind
            # The 872-call `deepseek-reasoner` 400 burst was diagnosed by
            # hand-probing the API live on 2026-08-01. Every one of those 872
            # discarded bodies already said "The supported API model names are
            # deepseek-v4-pro or deepseek-v4-flash".
            last_detail = summarize_error_body(raw)
            if not retryable:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err_kind, retryable = _classify(None, e)
            last_detail = redact(str(e) or type(e).__name__)
            if not retryable:
                break

    log_call({
        "provider": "deepseek", "model": model, "reviewer": reviewer,
        "input_tokens": 0, "output_tokens": 0,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status_code": last_status, "error_kind": last_err_kind, "retry_count": retry_count,
    })
    return CallResult(
        content=None, error_kind=last_err_kind, retryable=False,
        status_code=last_status,
        latency_ms=int((time.monotonic() - started) * 1000),
        error_detail=last_detail,
    )
