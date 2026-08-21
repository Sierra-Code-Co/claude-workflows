"""OpenAI provider client. Same chat-completions shape as deepseek.py.

Used as a cascade reviewer for high-risk paths (alongside google.py).
Replaces the prior anthropic.py cascade since the operator works with Claude
Code as the implementation model — a Claude judge on Claude-written code is
a same-family veto violation analogous to spec 130's `routeJudgeForCandidate`.

Default model: gpt-5.5 (operator's flagship). Override via REVIEW_PLAN_V2_OPENAI_MODEL env.
"""
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


DEFAULT_BASE = "https://api.openai.com"
DEFAULT_MODEL = "gpt-5.5"
RETRY_SLEEPS = (1.0, 4.0)
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
    """Call OpenAI's Chat Completions endpoint. Returns CallResult."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return CallResult(content=None, error_kind="auth", retryable=False, status_code=None)

    if max_tokens is None:
        # Resolved HERE, not as a default argument: a default is evaluated at
        # import time, so REVIEW_PLAN_V2_MAX_TOKENS set by a wrapper or a test
        # would be read before the override existed and silently ignored.
        max_tokens = resolve_max_tokens()

    if timeout is None:
        timeout = env_float("REVIEW_PLAN_V2_OPENAI_TIMEOUT", TIMEOUT_SEC)
    max_call_sec = env_float("REVIEW_PLAN_V2_OPENAI_MAX_CALL", MAX_CALL_SEC)
    # A budget checked only before retries is not a budget: with
    # REVIEW_PLAN_V2_OPENAI_TIMEOUT above MAX_CALL, attempt 0 alone overruns it.
    timeout = min(timeout, max_call_sec)

    if model is None:
        model = os.environ.get("REVIEW_PLAN_V2_OPENAI_MODEL", DEFAULT_MODEL)

    base = _validated_base(os.environ.get("OPENAI_API_BASE", DEFAULT_BASE))
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
        # NOT `max_tokens`. The gpt-5.x family rejects that parameter outright
        # with HTTP 400 `unsupported_parameter` — no tokens billed, no partial
        # answer, just a hard reject in ~200ms. This leg shipped with
        # `max_tokens` on 2026-05-09 and returned 400 on all 136 calls it ever
        # made until 2026-08-13. Verified live against gpt-5.5 both ways before
        # changing it: `max_tokens` → 400, `max_completion_tokens` → 200.
        "max_completion_tokens": max_tokens,
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
                    choice = (parsed.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    content = msg.get("content")
                    if is_blank(content):
                        # HTTP 200 but nothing usable. On reasoning models the
                        # usual cause is the token budget being consumed by
                        # reasoning tokens before any visible output — which
                        # `finish_reason` names exactly, so pass it through.
                        finish = choice.get("finish_reason") or "unknown"
                        usage = parsed.get("usage") or {}
                        reasoning = (
                            (usage.get("completion_tokens_details") or {})
                            .get("reasoning_tokens", 0)
                        )
                        last_err_kind = "empty"
                        last_detail = (
                            f"HTTP 200 but empty content (finish_reason={finish}, "
                            f"reasoning_tokens={reasoning}, budget={max_tokens}). "
                            "Raise max_completion_tokens if finish_reason=length."
                        )
                        break
                    usage = parsed.get("usage") or {}
                    log_call({
                        "provider": "openai", "model": model, "reviewer": reviewer,
                        "input_tokens": int(usage.get("prompt_tokens", 0)),
                        "output_tokens": int(usage.get("completion_tokens", 0)),
                        **budget_fields(int(usage.get("completion_tokens", 0)), max_tokens, reviewer),
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
            # The body of a non-2xx names the cause. Keeping it is the whole
            # difference between "openai leg failed" and "openai leg failed
            # because it is sending a parameter this model does not accept".
            last_detail = summarize_error_body(raw)
            if not retryable:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err_kind, retryable = _classify(None, e)
            last_detail = redact(str(e) or type(e).__name__)
            if not retryable:
                break

    log_call({
        "provider": "openai", "model": model, "reviewer": reviewer,
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
