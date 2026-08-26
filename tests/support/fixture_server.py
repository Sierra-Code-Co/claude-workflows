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
  4. {fixture}/any.json                     (provider- AND reviewer-agnostic)
  5. provider-shaped empty `[]` payload     (fallback)

Prefer tier 4 (`any.json`) for a fixture that just needs *some* finding to come
back. Tier 3 names a provider, and the miss is SILENT: when the broad-pass
default moved off deepseek, every `deepseek.json` stopped matching, the server
fell through to the empty payload, and five round-memory tests failed with "no
findings" — which reads as a bug in finding suppression, not a stale filename.
Reserve tier 3 for tests that are genuinely about one provider's wire shape.

Fixtures may be authored in ANY provider's response shape; `_extract_content`
pulls the findings string out and `_wrap_findings_for_provider` re-wraps it for
whoever asked (DeepSeek/OpenAI: choices[].message.content; Anthropic:
content[].text; Google: candidates[].content.parts[].text).
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


def request_prompts(raw: str) -> tuple[str, str] | None:
    """(system_prompt, user_prompt) from a recorded REQUEST body, any provider shape.

    Returns None if `raw` is not JSON or carries no recognisable prompt, so a caller
    can skip non-prompt traffic without distinguishing it from a parse failure.

    This exists because the request shapes differ and a test that hardcodes one is a
    test that stops asserting when the broad-pass default moves. test_context_delivery
    read `json.loads(raw)["messages"]` — the DeepSeek/OpenAI chat shape. Google sends
    `contents` and `system_instruction`, so `.get("messages")` returned None for every
    body, every prompt list came back empty, and three assertions about whether context
    reaches the provider silently stopped being about anything. They then failed on the
    `assertTrue(prompts)` guard, which reads as "context delivery is broken" rather than
    "the test cannot see the request". Context delivery was fine throughout.

    Note that is the SAME defect the response-side `any.json` tier fixed in the same
    commit, on the other side of the wire: a fixture named after one provider stopped
    matching, and the miss was silent. Both directions needed it; only one got it.

    The four shapes:
      deepseek, openai   messages[] with role system + role user
      anthropic          top-level `system`, messages[] with role user only
      google             system_instruction.parts[].text, contents[].parts[].text
    """
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None

    # Google. `system_instruction` is what google.py sends; the REST API also accepts
    # the camelCase spelling, so accept both rather than pinning today's choice.
    if "contents" in body:
        def _parts(node) -> str:
            """A `contents`/`system_instruction` entry's text, across part shapes.

            `isinstance(p.get("text"), str)`, matching `_text` below, not a bare
            `p.get("text", "")`. The default only covers a MISSING key; a part
            that carries `"text": None`, or an `inline_data`/`function_call` part
            whose `text` is a dict, returns a non-str and `"\\n".join` raises
            TypeError inside the fixture server's request handler. The chat-shape
            branch already guarded this and the google branch did not, which is
            the same defect this function exists to remove: a parser keyed to one
            provider's happy-path shape.
            """
            if not isinstance(node, dict):
                return ""
            return "\n".join(
                p.get("text", "") for p in node.get("parts") or []
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
        system = _parts(body.get("system_instruction") or body.get("systemInstruction"))
        # Filter by role, exactly as the chat-shape branch below does. This joined
        # EVERY `contents` entry regardless of role, while the chat branch takes
        # `role == "user"` only — so the same conversation read through the two
        # branches gave different answers. google.py sends a single `role: "user"`
        # entry today, so nothing is currently misread; the asymmetry matters if a
        # multi-turn body ever arrives (round memory is the obvious source), because
        # the model's own prior output would be folded into the "user" prompt and an
        # assertion looking for a path in the user half could be satisfied by the
        # model having mentioned it. `role` absent counts as user: a single-turn
        # body that omits it is still a prompt, and dropping it would empty the half.
        user = "\n".join(
            _parts(c) for c in body.get("contents") or []
            if isinstance(c, dict) and c.get("role", "user") == "user"
        )
        return (system, user) if (system or user) else None

    messages = body.get("messages")
    if not isinstance(messages, list):
        return None

    def _text(content) -> str:
        """A message's text, whether `content` is a string or a list of blocks.

        Both Anthropic and OpenAI accept `content` as a list of typed blocks
        (`[{"type": "text", "text": ...}]`) as well as a bare string, and
        Anthropic's top-level `system` takes the same two shapes. The providers in
        this repo all send strings today — test_request_prompt_extraction proves
        that by capturing their real payloads — so this is not a live bug. It is
        here because of what the failure would look like if one switched: the
        string-only version returned "" for every block-list message, so the
        prompt lists came back empty, and the three assertions in
        test_context_delivery would fail on their `assertTrue(prompts)` guard
        reading "context delivery is broken". That is the exact misdiagnosis this
        whole function was written to remove — a fixture named for one provider
        and a parser keyed to one wire format are the same defect, and so is a
        parser keyed to one spelling of a field within the right format.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and isinstance(b.get("text"), str)
            )
        return ""

    def _joined(role: str) -> str:
        return "\n".join(
            _text(m.get("content")) for m in messages
            if isinstance(m, dict) and m.get("role") == role
        )

    # Anthropic carries the system prompt out of band; chat-shape providers carry it
    # as a message. Concatenating both covers either without a provider branch.
    system = "\n".join(p for p in (_text(body.get("system")), _joined("system")) if p)
    user = _joined("user")
    return (system, user) if (system or user) else None


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
            # Provider- and reviewer-agnostic. Last so the specific tiers still
            # win, but present so a fixture need not be named after whichever
            # provider happens to be the current broad-pass default.
            FIXTURES_DIR / fixture / "any.json",
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
