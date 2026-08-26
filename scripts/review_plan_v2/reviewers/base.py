"""Reviewer ABC. Loads a system prompt from disk, calls a provider, parses Findings."""
from __future__ import annotations

import json
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..providers._errors import is_blank
from ..types import CallResult, ChangeManifest, FileChange, Finding

PROMPT_DIR = Path(__file__).parent.parent / "prompts"


class ProviderCallFailed(RuntimeError):
    """A reviewer could not obtain a review because its provider call failed.

    Raised rather than returned. `run()` used to answer a failed call with
    `return []` — indistinguishable, to every caller upstream, from "this
    reviewer looked and found nothing clean". That single line is what let the
    OpenAI cascade leg report success while failing 136 consecutive calls:
    the orchestrator counts a task as failed only when it raises, so a
    swallowed failure left `failed_task_count` at 0, the coverage banner
    silent, and the exit code 0.

    Raising puts the failure through machinery that already exists and already
    works: `run_with_cap` captures per-task exceptions (so one dead leg cannot
    abort the run), the orchestrator prints the WARNING and increments the
    counter, and `exit_code_for` maps any non-zero count to exit 2.
    """

    def __init__(self, reviewer: str, path: str, result: CallResult):
        self.reviewer = reviewer
        self.path = path
        self.result = result
        detail = result.error_detail or "no detail returned by provider"
        status = result.status_code if result.status_code is not None else "no-response"
        super().__init__(f"{result.error_kind} (HTTP {status}) — {detail}")


@dataclass
class Reviewer(ABC):
    name: str  # security | correctness | tests | consistency
    prompt_filename: str
    provider_call: Callable[..., CallResult]  # signature: (system, user, reviewer=...) -> CallResult
    model: str
    needs_manifest: bool = False

    def system_prompt(self) -> str:
        path = PROMPT_DIR / self.prompt_filename
        return path.read_text(encoding="utf-8")

    def build_user_prompt(self, chunk: FileChange, manifest: ChangeManifest | None,
                          context_text: str = "") -> str:
        parts: list[str] = []
        if self.needs_manifest and manifest is not None:
            from ..change_manifest import render_for_prompt
            parts.append(render_for_prompt(manifest))
            parts.append("")
        # US5: definitions of symbols this diff references but does not show.
        # Placed BEFORE the diff so it is read as background rather than as an
        # afterthought appended to the thing under review.
        if context_text:
            parts.append(context_text)
            parts.append("")
        parts.append(f"[File: {chunk.path} | language: {chunk.language or 'unknown'}]")
        parts.append("```diff")
        parts.append(chunk.diff_text.rstrip("\n"))
        parts.append("```")
        return "\n".join(parts)

    def run(self, chunk: FileChange, manifest: ChangeManifest | None = None,
            context_text: str = "") -> list[Finding]:
        result = self.provider_call(
            self.system_prompt(),
            self.build_user_prompt(chunk, manifest, context_text),
            model=self.model,
            reviewer=self.name,
        )
        if result.error_kind is not None or is_blank(result.content):
            raise ProviderCallFailed(self.name, chunk.path, result)
        return parse_findings(result.content, source=self.name, default_file=chunk.path)


def parse_findings(content: str, source: str, default_file: str) -> list[Finding]:
    """Parse the JSON-formatted findings array out of a reviewer's text response.

    Tolerates: bare JSON array, JSON wrapped in ```json fences, trailing prose,
    leading prose. Returns empty list on parse failure.
    """
    text = content.strip()
    # Strip markdown fences if present
    if "```" in text:
        in_fence = False
        chunks: list[str] = []
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                chunks.append(line)
        if chunks:
            text = "\n".join(chunks).strip()

    # Try whole text first, then bracket-extracted
    candidates = [text]
    start = text.find("[")
    end = text.rfind("]")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        out: list[Finding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                # Explicit None-coalesce so JSON nulls don't become the string "None"
                file_v = item.get("file")
                file_v = file_v if file_v is not None else default_file
                msg_v = item.get("message")
                msg_v = msg_v if msg_v is not None else ""
                sev_v = item.get("severity")
                sev_v = sev_v if sev_v is not None else "nit"
                cat_v = item.get("category")
                cat_v = cat_v if cat_v is not None else "style"
                line_raw = item.get("line", 1)
                line_v = int(line_raw) if line_raw is not None else 1
                line_end_raw = item.get("line_end")
                line_end_v = int(line_end_raw) if line_end_raw is not None else None
                # The claim rides through UNCOERCED and UNVALIDATED on purpose.
                # A reviewer reads untrusted diff content, so this value is
                # attacker-influenceable (FR-022); sanitising it here would put
                # a security decision in the parser, far from the allowlist that
                # actually enforces it. It is validated in verification.classify
                # and resolved in verification.verify, and anything malformed
                # becomes `unchecked` WITH a log line rather than being quietly
                # discarded — a dropped claim renders identically to a finding
                # that never made one.
                out.append(Finding(
                    file=str(file_v),
                    line=line_v,
                    line_end=line_end_v,
                    severity=str(sev_v),
                    category=str(cat_v),
                    message=str(msg_v),
                    sources=[source],
                    claim=item.get("claim"),
                ))
            except (TypeError, ValueError):
                continue
        return out
    return []
