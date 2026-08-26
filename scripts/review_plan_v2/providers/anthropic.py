"""Anthropic Messages API client. Same shape as deepseek.py.

NOT WIRED IN. Nothing imports this module — the cascade moved to OpenAI +
Google in #25 because Claude reviewing Claude-Code-written code is a
same-family self-grading violation. The only remaining reference is a row in
orchestrator's pricing table marked "legacy / replay only".

It is kept, and kept current with its siblings' error handling, so that
reviving it cannot silently reintroduce the failure this file's siblings were
fixed for on 2026-08-13: a provider that discards its HTTP error body and
reports a failed call as an empty-but-successful review. A dead sibling with
an older contract is exactly the landmine someone steps on when they wire it
back up.
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
from ._errors import is_blank, redact, summarize_error_body

DEFAULT_BASE = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-4-6"
TIMEOUT_SEC = 30.0
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


def call(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL,
         max_tokens: int = 8192, timeout: float = TIMEOUT_SEC,
         reviewer: str = "unknown") -> CallResult:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return CallResult(content=None, error_kind="auth", retryable=False, status_code=None)

    base = _validated_base(os.environ.get("ANTHROPIC_API_BASE", DEFAULT_BASE))
    url = f"{base}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    test_fix = os.environ.get("REVIEW_PLAN_V2_TEST_FIXTURE")
    if test_fix:
        headers["X-Test-Fixture"] = test_fix
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    last_err_kind: str | None = "unknown"
    last_status: int | None = None
    last_detail: str | None = None
    started = time.monotonic()
    retry_count = 0

    for attempt in range(1 + len(RETRY_SLEEPS)):
        if attempt > 0:
            time.sleep(RETRY_SLEEPS[attempt - 1])
            retry_count += 1
        try:
            status, raw = _post_once(url, headers, payload, timeout)
            last_status = status
            kind, retryable = _classify(status, None)
            if kind is None:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                    blocks = parsed.get("content") or []
                    text_parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                    content = "".join(text_parts)
                    if is_blank(content):
                        last_err_kind = "empty"
                        last_detail = (
                            "HTTP 200 but empty content (stop_reason="
                            f"{parsed.get('stop_reason') or 'unknown'}, budget={max_tokens})"
                        )
                        break
                    usage = parsed.get("usage") or {}
                    log_call({
                        "provider": "anthropic", "model": model, "reviewer": reviewer,
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "status_code": status, "error_kind": None, "retry_count": retry_count,
                    })
                    return CallResult(
                        content=content, error_kind=None, retryable=False,
                        status_code=status,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        input_tokens=int(usage.get("input_tokens", 0)),
                        output_tokens=int(usage.get("output_tokens", 0)),
                    )
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    last_err_kind = "parse"
                    last_detail = f"could not parse a 2xx response body: {type(e).__name__}"
                    break
            last_err_kind = kind
            last_detail = summarize_error_body(raw)
            if not retryable:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err_kind, retryable = _classify(None, e)
            last_detail = redact(str(e) or type(e).__name__)
            if not retryable:
                break

    log_call({
        "provider": "anthropic", "model": model, "reviewer": reviewer,
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
