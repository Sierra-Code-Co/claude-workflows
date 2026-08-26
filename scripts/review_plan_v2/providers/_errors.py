"""Shared provider-failure helpers.

Every provider in this package read its HTTP error body off the wire and then
threw it away. The OpenAI cascade leg spent 2026-05-09 → 2026-08-13 returning
HTTP 400 on all 136 calls it ever made, while the body of every one of those
responses said, verbatim:

    Unsupported parameter: 'max_tokens' is not supported with this model.
    Use 'max_completion_tokens' instead.

The remedy was fetched 136 times and discarded 136 times. These helpers exist
so a dead leg names its own cause on the first run instead of the 137th.

Two hard constraints:

* **Never telemetry.** FR-015 bars message bodies from `calls.jsonl`. Summaries
  produced here ride `CallResult.error_detail` to stderr and stop there.
* **Never a secret.** `google.py` passes the API key as a URL query parameter,
  so any echoed request context is a live credential. `redact()` runs on every
  path out of this module, including the non-JSON fallback.
"""
from __future__ import annotations

import json
import re

MAX_DETAIL_CHARS = 300

# Ordered most-specific first. Each pattern keeps its label so a redacted
# message still says WHICH kind of credential appeared — useful for diagnosis,
# useless to an attacker.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{8,}"), "AIza***"),
    # HTTP auth schemes put the credential AFTER a space, so a value pattern
    # that stops at whitespace masks the scheme and leaks the secret — an
    # `authorization: Basic dXNlcjpwdw==` became `authorization: *** dXNlcjpwdw==`
    # until this was split out. Base64 padding (`=`, `+`, `/`) must be in the
    # value class or the tail survives.
    (re.compile(r"(?i)\b(Bearer|Basic|Token|Digest)\s+[A-Za-z0-9._\-=+/]{4,}"), r"\1 ***"),
    # Credential-bearing fields in every delimiter style a provider might echo:
    # query/form (`key=v`), JSON (`"api_key": "v"`), and headers
    # (`x-api-key: v`). Covering only `=` left the JSON and header shapes
    # exposed, and a provider quoting the offending request back at you is
    # exactly when a body is most likely to contain one.
    (
        re.compile(
            r"""(?ix)
            (["']?(?:x-)?(?:api[-_]?key|apikey|key|token|secret|password|authorization)["']?
             \s*[:=]\s*)
            (?: "[^"]*"        # quoted value — consume THROUGH the closing quote,
              | '[^']*'        # so a secret containing spaces cannot keep its tail
              | [^\s,;}&"']+   # bare value — ends at whitespace or a delimiter
            )
            """
        ),
        r"\1***",
    ),
    # Backstop for key formats not yet invented. Deliberately narrow: 32+ chars
    # mixing letters AND digits, no underscores. The obvious `[A-Za-z0-9_-]{32,}`
    # is too greedy — it eats long snake_case symbols (a test name like
    # `test_cascade_invokes_a_leg_other_than_the_broad_provider_on_high_risk`
    # is 69 chars) and
    # turns the diagnostic into `***`, which defeats the point of keeping the
    # body at all. Requiring a digit and banning `_` keeps identifiers readable
    # while still catching opaque credential-shaped runs. A git SHA matches and
    # gets redacted; harmless.
    (re.compile(r"\b(?=[A-Za-z0-9\-]*[0-9])(?=[A-Za-z0-9\-]*[A-Za-z])[A-Za-z0-9\-]{32,}\b"), "***"),
)


def redact(text: str) -> str:
    """Strip anything credential-shaped. Applied to every outbound summary."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _extract_message(text: str) -> str:
    """Pull the human-readable message out of a provider error envelope.

    OpenAI/DeepSeek: {"error": {"message": ...}}
    Google:          {"error": {"message": ..., "status": ...}}
    Anything else:   fall back to the raw text.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(parsed, dict):
        return text
    err = parsed.get("error")
    if isinstance(err, dict):
        for key in ("message", "type", "status", "code"):
            value = err.get(key)
            if isinstance(value, str) and value:
                return value
    elif isinstance(err, str) and err:
        return err
    message = parsed.get("message")
    if isinstance(message, str) and message:
        return message
    return text


def summarize_error_body(raw: bytes | None, limit: int = MAX_DETAIL_CHARS) -> str | None:
    """Turn an HTTP error body into one short, redacted, operator-facing line.

    Returns None only when there is genuinely nothing to say, so a caller can
    distinguish "no body" from "a body we could not parse" (the latter comes
    back as its own truncated text rather than silently vanishing).
    """
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    message = " ".join(_extract_message(text).split())
    if not message:
        return None
    message = redact(message)
    if len(message) > limit:
        message = message[:limit].rstrip() + "…"
    return message


def is_blank(content: str | None) -> bool:
    """True when a provider technically answered but said nothing usable.

    Reasoning models make this a live failure mode rather than a theoretical
    one: `max_completion_tokens` is spent on reasoning tokens FIRST, so a
    budget that is merely too small returns HTTP 200, `finish_reason:
    "length"`, and `content: ""`. Verified live against gpt-5.5 — a 16-token
    budget produced 107 reasoning tokens and an empty string.

    Treating that as success is strictly worse than the HTTP 400 it replaced:
    the run reports a healthy leg that contributed no findings.
    """
    return content is None or not content.strip()
