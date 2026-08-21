"""http.server-based mock for DeepSeek + OpenAI + Anthropic + Google providers.

Returns canned JSON keyed by X-Test-Fixture header. Provider detection:
- /v1/chat/completions: parse body's `model` field — `gpt-*` → openai, otherwise deepseek
  (both providers use the OpenAI-compatible chat-completions URL pattern)
- /v1/messages: anthropic (Messages API)
- /v1beta/models/{model}:generateContent: google (Gemini's generateContent shape)

Fixture file lookup order (per request):
  1. {fixture}/{provider}-{reviewer}.json   (most specific)
  2. {fixture}/{reviewer}.json              (provider-agnostic)
  3. {fixture}/{provider}.json              (reviewer-agnostic)
  4. provider-shaped empty `[]` payload     (fallback)

The fixture JSON must already be in the provider's response shape (DeepSeek/OpenAI:
choices[].message.content; Anthropic: content[].text; Google: candidates[].content.parts[].text).
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "responses"

# /v1beta/models/{model}:generateContent[?key=...] — capture model id for routing.
#
# The optional query string is load-bearing. This pattern was anchored `$`
# immediately after `:generateContent`, but google.py passes its API key as a
# query parameter and BaseHTTPRequestHandler puts the full query into
# `self.path`, so a real request arrives as
# `/v1beta/models/gemini-3.1-pro-preview:generateContent?key=test-key` and
# never matched. Every Gemini call in the integration suite 404'd, so the
# google cascade leg was never actually exercised by any test — invisible
# until `test_cascade` started asserting that a called leg SUCCEEDED rather
# than merely appearing in the attempt counter.
_GEMINI_PATH_RE = re.compile(r"^.*/v1beta/models/[^:/]+:generateContent(?:\?.*)?$")


# Module-level request counter so tests can assert "no LLM calls" contracts.
_request_count_lock = threading.Lock()
_request_count = 0


def reset_request_count() -> None:
    global _request_count
    with _request_count_lock:
        _request_count = 0


def get_request_count() -> int:
    with _request_count_lock:
        return _request_count


def _bump_request_count() -> None:
    global _request_count
    with _request_count_lock:
        _request_count += 1


# Captured request bodies, so a test can assert what the reviewers were actually
# SENT rather than only how many times they were called. US5 adds context to the
# prompt, and "the assembler produced it" is a different claim from "it reached
# the provider" — the T047 defect was exactly that gap, one flag wide.
_bodies_lock = threading.Lock()
_request_bodies: list[str] = []


def reset_request_bodies() -> None:
    with _bodies_lock:
        _request_bodies.clear()


def get_request_bodies() -> list[str]:
    with _bodies_lock:
        return list(_request_bodies)


def _record_request_body(body_raw: bytes) -> None:
    with _bodies_lock:
        _request_bodies.append(body_raw.decode("utf-8", errors="replace"))


def _empty_payload(provider: str) -> dict:
    """Provider-shaped empty findings payload, used when no fixture file matches."""
    if provider in ("deepseek", "openai"):
        return {
            "choices": [{"message": {"content": "[]"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    if provider == "anthropic":
        return {
            "content": [{"type": "text", "text": "[]"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    # google
    return {
        "candidates": [{"content": {"parts": [{"text": "[]"}]}}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
    }


def _wrap_findings_for_provider(provider: str, content: str) -> dict:
    """Re-shape a fixture's findings JSON-string into the provider's response envelope.

    Input shape (canonical): {"choices":[{"message":{"content": "<JSON-string of findings>"}}], "usage": {...}}
    or {"content":[{"text": "..."}]} or any provider's native shape.

    For backward compat with existing fixtures (which were authored in DeepSeek's shape),
    we attempt to extract the inner content string and re-wrap for the requesting provider.
    """
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100},
    } if provider in ("deepseek", "openai") else (
        {
            "content": [{"type": "text", "text": content}],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        } if provider == "anthropic" else {
            "candidates": [{"content": {"parts": [{"text": content}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 100},
        }
    )


def _extract_content(provider: str, raw: dict) -> str | None:
    """Pull the findings JSON-string out of a fixture in any provider's native shape.

    Lets a single fixture file (authored in any one shape) serve any requesting
    provider — the fixture server re-wraps as needed. Returns None if no recognizable
    content field is found.
    """
    # DeepSeek / OpenAI shape
    try:
        msg = (raw.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
    except (AttributeError, KeyError, IndexError, TypeError):
        pass
    # Anthropic shape
    try:
        blocks = raw.get("content") or []
        text_parts = [b.get("text", "") for b in blocks if isinstance(b, dict)]
        joined = "".join(text_parts)
        if joined:
            return joined
    except (AttributeError, TypeError):
        pass
    # Google shape
    try:
        candidates = raw.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        joined = "".join(text_parts)
        if joined:
            return joined
    except (AttributeError, KeyError, IndexError, TypeError):
        pass
    return None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence noisy default logger
        return

    def _detect_provider(self, body_raw: bytes) -> str | None:
        """Detect which provider sent this request based on URL + body shape."""
        if self.path.endswith("/v1/messages"):
            return "anthropic"
        if _GEMINI_PATH_RE.match(self.path):
            return "google"
        if self.path.endswith("/v1/chat/completions") or "/v1/chat/completions" in self.path:
            # OpenAI + DeepSeek collide on this URL — disambiguate by body's model field
            try:
                req = json.loads(body_raw.decode("utf-8"))
                model = (req.get("model") or "").lower()
                if model.startswith("gpt-") or model.startswith("o1-") or model.startswith("o3-"):
                    return "openai"
                return "deepseek"
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                # Body unreadable → fall back to deepseek (legacy default)
                return "deepseek"
        return None

    def _detect_reviewer(self, provider: str, body_raw: bytes) -> str:
        """Sniff reviewer name from request body's system prompt."""
        try:
            req = json.loads(body_raw.decode("utf-8"))
            system_text = ""
            if provider in ("deepseek", "openai"):
                for msg in req.get("messages", []):
                    if msg.get("role") == "system":
                        system_text = msg.get("content", "") or ""
                        break
            elif provider == "anthropic":
                system_text = req.get("system", "") or ""
            elif provider == "google":
                # Gemini stashes system prompt under system_instruction.parts[].text
                parts = (req.get("system_instruction") or {}).get("parts") or []
                system_text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            for r in ("security", "correctness", "tests", "consistency"):
                marker = f"You are the **{r}** code reviewer"
                if marker in system_text:
                    return r
        except (json.JSONDecodeError, KeyError, AttributeError, UnicodeDecodeError):
            pass
        return "default"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body_raw = self.rfile.read(length) if length else b""

        provider = self._detect_provider(body_raw)
        if provider is None:
            self.send_response(404)
            self.end_headers()
            return
        _bump_request_count()
        _record_request_body(body_raw)

        # Sanitize fixture-name header
        raw_fixture = self.headers.get("X-Test-Fixture", "01-clean")
        parts = Path(raw_fixture).parts
        if any(p in (".", "..") or "/" in p or "\\" in p for p in parts):
            fixture = "01-clean"
        else:
            fixture = Path(raw_fixture).name or "01-clean"
        try:
            FIXTURES_DIR.resolve(strict=False)
            candidate_root = (FIXTURES_DIR / fixture).resolve(strict=False)
            candidate_root.relative_to(FIXTURES_DIR.resolve(strict=False))
        except ValueError:
            fixture = "01-clean"

        reviewer = self._detect_reviewer(provider, body_raw)

        candidates = [
            FIXTURES_DIR / fixture / f"{provider}-{reviewer}.json",
            FIXTURES_DIR / fixture / f"{reviewer}.json",
            FIXTURES_DIR / fixture / f"{provider}.json",
        ]
        payload = None
        for c in candidates:
            if c.exists():
                raw_payload = json.loads(c.read_text(encoding="utf-8"))
                # If the fixture is in a different provider's shape than the
                # requester, re-wrap so the requester can parse it. This means
                # one fixture file authored in (e.g.) DeepSeek shape works for
                # OpenAI + Google + Anthropic requests too.
                content = _extract_content(provider, raw_payload)
                if content is not None:
                    # Check if the raw payload is already in the requesting
                    # provider's shape — if yes, return as-is to preserve any
                    # extra fields. Otherwise re-wrap.
                    if (
                        (provider in ("deepseek", "openai") and "choices" in raw_payload)
                        or (provider == "anthropic" and "content" in raw_payload and isinstance(raw_payload.get("content"), list))
                        or (provider == "google" and "candidates" in raw_payload)
                    ):
                        payload = raw_payload
                    else:
                        payload = _wrap_findings_for_provider(provider, content)
                else:
                    payload = raw_payload  # unparseable but exists; return as-is
                break
        if payload is None:
            payload = _empty_payload(provider)

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FixtureServer:
    def __init__(self):
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start on an OS-assigned port. Returns base URL like http://127.0.0.1:54321"""
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
