"""Resolve a claim against the checkout (T026, T027, T028, T028a, T031).

Three methods, and the boundary between them is a security boundary, not a
taxonomy.

  enumerate  — count occurrences. Pure Python string search, or a REGISTERED
               structural rule. No subprocess takes reviewer text.
  typecheck  — read a declaration. ast-grep with a FIXED pattern; the reviewer's
               identifier is compared against captured metavariables in Python,
               never interpolated into the pattern.
  execute    — not implemented. Resolves to `unverifiable` with a log line
               (FR-024), because the sandboxing model is not specified yet and a
               verification step that runs attacker-influenceable input inside
               the review pipeline is an RCE vector wearing a safety vest.

THE RULE THIS MODULE MUST NEVER BREAK: no path through here returns `confirmed`
without an affirmative observation. Every failure — a rejected input, a missing
declaration, a timeout, an unexpected exception — resolves to `unverifiable` or
`unchecked`, both of which RENDER the finding with a marker. Silently promoting
an unverified claim to `confirmed` would make this module worse than not having
it: it would launder a guess into a fact.

FR-022/FR-023 in one sentence: the reviewer read the diff, so anything it emits
is attacker-influenceable, so `check.input` is resolved through an allowlist
before it is used for anything at all.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..paths import contained
from .classify import (
    CONFIRMED,
    REFUTED,
    UNCHECKED,
    UNVERIFIABLE,
    Check,
    Claim,
    method_for_kind,
)

# --- limits -----------------------------------------------------------------
# Every one of these is a REPORTED cap, never a silent one. A truncated scan
# that renders as a completed scan is the defect this portfolio exists to close,
# so hitting any of them yields `unchecked` with the cap named in the detail.
MAX_INPUT_CHARS = 256
MAX_LITERAL_CHARS = 64
MAX_FILE_BYTES = 2_000_000
MAX_FILES_SCANNED = 20_000
DEFAULT_TIMEOUT_SEC = 20.0
# How many files a declaration search may look at, and how many paths ride in
# one ast-grep invocation. ast-grep accepts many paths at once and reports the
# file per match, so batching turns "one subprocess per candidate file" into
# roughly len(files)/400 — the difference between ~400 spawns and 5 on a
# mid-size checkout. The chunk keeps argv well under ARG_MAX.
MAX_DECL_FILES = 2_000
PATHS_PER_INVOCATION = 400

SCOPES = ("tests", "src", "all")

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_RE_IDENT = re.compile(rf"^{_IDENT}$")
# A dotted member path (`ts.isCallExpression`) is still just identifiers.
_RE_DOTTED = re.compile(rf"^{_IDENT}(\.{_IDENT})*$")
_RE_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_RE_RELPATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}$")
_RE_LITERAL = re.compile(r'^"([^"\n\r\t]{1,%d})"$' % MAX_LITERAL_CHARS)

_TEXT_SUFFIXES = {
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".sh", ".bash", ".yml", ".yaml", ".json", ".md", ".sql", ".svelte",
}
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".svelte-kit", ".pytest_cache", ".mypy_cache", "target", "coverage",
}

# ast-grep patterns are CONSTANTS. Nothing derived from a claim is ever
# interpolated into one; captured metavariables are compared in Python instead.
_DECL_PATTERNS: tuple[str, ...] = (
    "function $NAME($$$A): $RET { $$$B }",
    "const $NAME = ($$$A): $RET => $$$B",
    "export function $NAME($$$A): $RET { $$$B }",
)
_INTERFACE_PATTERN = "interface $NAME { $$$BODY }"
_TYPE_ALIAS_PATTERN = "type $NAME = { $$$BODY }"


def _default_log(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class Verdict:
    verdict: str
    detail: str | None = None


@dataclass(frozen=True)
class ResolvedInput:
    """What a `check.input` was allowed to mean. Nothing else is permitted."""
    form: str          # rule | symbol | literal
    scope: str         # tests | src | all
    name: str          # rule id, identifier, or literal needle
    path: str | None = None  # repo-relative file, when the claim named one


class InputRejected(ValueError):
    """`check.input` did not match the allowlist. Never fall back to using it."""


# --- T028a: the allowlist ----------------------------------------------------


def resolve_input(
    check: Check,
    repo_root: Path,
    *,
    rule_ids: frozenset[str] | set[str] = frozenset(),
) -> ResolvedInput:
    """Map `check.input` onto exactly one permitted form, or reject it.

    Permitted (FR-023): a registered structural-rule id, a symbol path resolved
    against the checkout, a type name, or — for `count` claims about syntax
    rather than identifiers — a quoted literal used solely as a search needle.

    A literal is safe *because of where it can go*, not because of what it says:
    it is only ever an argument to `str.count`. It never reaches a shell, never
    becomes part of a pattern, never names a file. `"; rm -rf / #"` as a needle
    finds nothing and does nothing.
    """
    raw = check.input
    if not isinstance(raw, str) or not raw:
        raise InputRejected("check.input must be a non-empty string")
    if len(raw) > MAX_INPUT_CHARS:
        raise InputRejected(f"check.input exceeds {MAX_INPUT_CHARS} chars")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        raise InputRejected("check.input contains control characters")

    # A registered rule id is matched BEFORE any parsing, and only against ids
    # we discovered ourselves by listing rules/ — the string never becomes a path.
    if raw in rule_ids:
        return ResolvedInput(form="rule", scope="all", name=raw)

    # A scope prefix is recognised only when the segment before the first colon
    # IS a scope. Anything else falls through to the path/identifier rules below
    # and is rejected there — `web/…/describe-thrown.ts::describeThrown` must not
    # be read as a scope named "web/…​/describe-thrown.ts".
    scope = "all"
    rest = raw
    head, sep, tail = raw.partition(":")
    if sep and head in SCOPES:
        scope, rest = head, tail

    lit = _RE_LITERAL.match(rest)
    if lit:
        return ResolvedInput(form="literal", scope=scope, name=lit.group(1))

    path: str | None = None
    name = rest
    if "::" in rest:
        path, _, name = rest.partition("::")
        if not _RE_RELPATH.match(path) or ".." in Path(path).parts or Path(path).is_absolute():
            raise InputRejected(f"path {path!r} is not a safe repo-relative path")
        target = (repo_root / path).resolve()
        if not contained(target, repo_root):
            raise InputRejected(f"path {path!r} escapes the checkout")
        if not target.is_file():
            raise InputRejected(f"path {path!r} does not resolve to a file in the checkout")

    if not _RE_DOTTED.match(name):
        raise InputRejected(f"{name!r} is not an identifier, type name, or registered rule id")
    return ResolvedInput(form="symbol", scope=scope, name=name, path=path)


# --- file selection ----------------------------------------------------------


def _is_test_path(rel: str) -> bool:
    low = rel.lower()
    return (
        ".test." in low or ".spec." in low
        or "/tests/" in f"/{low}" or "/__tests__/" in f"/{low}"
        or low.startswith("tests/")
    )


def _candidate_files(repo_root: Path, scope: str) -> tuple[list[Path], bool]:
    """Return (files, truncated). `truncated` is reported, never swallowed."""
    out: list[Path] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix not in _TEXT_SUFFIXES:
                continue
            # os.walk does not DESCEND into symlinked directories, but it still
            # yields symlinked files. Following one reads a file outside the
            # checkout and attributes its contents to the repo — a claim about
            # code that is not in the code under review.
            if p.is_symlink():
                continue
            rel = str(p.relative_to(repo_root))
            is_test = _is_test_path(rel)
            if scope == "tests" and not is_test:
                continue
            if scope == "src" and is_test:
                continue
            out.append(p)
            if len(out) >= MAX_FILES_SCANNED:
                truncated = True
                return out, truncated
    return out, truncated


def _count_occurrences(
    files: list[Path], needle: str, *, word: bool,
) -> tuple[int, list[str], list[str]]:
    """Return (count, files_with_hits, files_NOT_read).

    The third element exists because skipping a file silently corrupts the
    answer, not just its precision. A `symbol_absent` claim over a corpus where
    the one file defining the symbol was skipped for size comes back CONFIRMED —
    the verifier stating, with a mechanism's authority, that something is absent
    when it simply did not look. Unread files make the count a floor, and a floor
    cannot settle an absence.
    """
    pattern = re.compile(rf"\b{re.escape(needle)}\b") if word else None
    total = 0
    where: list[str] = []
    unread: list[str] = []
    for p in files:
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                unread.append(str(p))
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            unread.append(f"{p} ({e.__class__.__name__})")
            continue
        n = len(pattern.findall(text)) if pattern else text.count(needle)
        if n:
            total += n
            where.append(str(p))
    return total, where, unread


# --- T026: enumerate ---------------------------------------------------------


def _run_rule(rule_path: Path, repo_root: Path, timeout: float) -> int:
    proc = subprocess.run(
        ["ast-grep", "scan", "--rule", str(rule_path), "--json", "--", str(repo_root)],
        capture_output=True, text=True, timeout=timeout, cwd=str(repo_root),
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ast-grep exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    return len(json.loads(proc.stdout or "[]"))


def _verify_enumerate(
    claim: Claim, resolved: ResolvedInput, repo_root: Path, *,
    rule_paths: dict[str, Path], timeout: float,
) -> Verdict:
    if resolved.form == "rule":
        observed = _run_rule(rule_paths[resolved.name], repo_root, timeout)
        where: list[str] = []
    else:
        files, truncated = _candidate_files(repo_root, resolved.scope)
        if truncated:
            return Verdict(UNCHECKED, f"scan stopped at the {MAX_FILES_SCANNED}-file cap; "
                                      "the count would be a floor, not a count")
        observed, where, unread = _count_occurrences(
            files, resolved.name, word=(resolved.form == "symbol"),
        )
        if unread:
            sample = ", ".join(Path(u).name for u in unread[:3])
            return Verdict(UNCHECKED,
                           f"{len(unread)} file(s) in scope could not be read "
                           f"({sample}), so the count is a floor and cannot "
                           "settle this claim")

    scope_label = f"{resolved.scope} files"
    sample = ", ".join(sorted(w.split("/")[-1] for w in where)[:3])

    if claim.kind == "symbol_exists":
        if observed:
            return Verdict(CONFIRMED, f"{observed} occurrence(s) in {scope_label} ({sample})")
        return Verdict(REFUTED, f"no occurrence of {resolved.name!r} in {scope_label}")

    if claim.kind == "symbol_absent":
        if observed:
            return Verdict(REFUTED, f"{observed} occurrence(s) in {scope_label} ({sample})")
        return Verdict(CONFIRMED, f"absent from {scope_label}")

    if claim.kind == "count":
        try:
            expected = int(claim.expected.strip())
        except ValueError:
            return Verdict(UNVERIFIABLE,
                           f"expected {claim.expected!r} is not a number, so there is "
                           "nothing to compare the count against")
        if observed == expected:
            return Verdict(CONFIRMED, f"{observed} in {scope_label}, as claimed")
        detail = f"observed {observed} in {scope_label}, claim said {expected}"
        return Verdict(REFUTED, detail + (f" ({sample})" if sample else ""))

    return Verdict(UNVERIFIABLE, f"kind {claim.kind!r} is not answerable by enumerate")


# --- T027: typecheck ---------------------------------------------------------


def _ast_grep_pattern(pattern: str, paths: Sequence[Path], timeout: float) -> list[dict]:
    """Run one CONSTANT pattern over many files, batched.

    `pattern` is always a module-level constant; the claim's identifier is
    compared against captured metavariables afterwards, in Python. Nothing
    derived from a claim is ever interpolated into an ast-grep pattern
    (FR-023) — and the file paths come from our own directory walk, not from
    the claim.
    """
    # Grouped by GRAMMAR, not lumped under --lang ts. `.tsx` parsed as `ts`
    # returns [] — silently, with exit 0 — so every declaration in a .tsx file
    # was invisible and reported as "no declaration found". A wrong reason, not
    # just a miss: the declaration is there, we handed the parser the wrong
    # grammar. Verified 2026-08-15: --lang ts on a .tsx file yields [], --lang
    # tsx yields the match.
    by_lang: dict[str, list[Path]] = {}
    for p in paths:
        by_lang.setdefault("tsx" if p.suffix == ".tsx" else "ts", []).append(p)

    out: list[dict] = []
    for lang, group in by_lang.items():
        for i in range(0, len(group), PATHS_PER_INVOCATION):
            chunk = [str(p) for p in group[i:i + PATHS_PER_INVOCATION]]
            proc = subprocess.run(
                # `--` before the paths. Without it a repository file named
                # `-dash.ts` is parsed as an OPTION — ast-grep exits with
                # "unexpected argument '-d' found" and verification dies for the
                # whole checkout. The paths come from our own walk, but their
                # NAMES come from the repo under review, which is attacker
                # -influenceable content (FR-022).
                ["ast-grep", "run", "--lang", lang, "--pattern", pattern,
                 "--json=compact", "--", *chunk],
                capture_output=True, text=True, timeout=timeout,
            )
            if proc.returncode not in (0, 1):
                raise RuntimeError(
                    f"ast-grep exited {proc.returncode}: {proc.stderr.strip()[:200]}"
                )
            out.extend(json.loads(proc.stdout or "[]"))
    return out


def _single(match: dict, var: str) -> str | None:
    got = match.get("metaVariables", {}).get("single", {}).get(var)
    return got["text"] if got else None


def _members_from_body(match: dict) -> list[str]:
    """Property names out of an interface / type-alias body.

    ast-grep hands back the body as a token list — `['errName: string', ';',
    'errMessage: string', ...]` — so the names come from splitting each member on
    its colon. Reading the AST rather than regexing the file is Principle III:
    the last three times this fleet regexed over call syntax it was wrong three
    times.
    """
    items = match.get("metaVariables", {}).get("multi", {}).get("BODY", [])
    names: list[str] = []
    for it in items:
        text = it.get("text", "").strip()
        if not text or text in (";", ","):
            continue
        # LAST token before the colon, not the whole left side. `readonly
        # errName: string` has head "readonly errName", which failed the
        # identifier check and dropped the member silently — and a dropped
        # member makes an expected field look ABSENT, which REFUTES the finding.
        # That is the worst available direction to be wrong in: a true finding
        # deleted on the strength of a parsing gap. Index signatures
        # (`[key: string]: T`) still drop, correctly — they name no member.
        head = text.split(":", 1)[0].strip()
        tokens = head.split()
        candidate = tokens[-1].rstrip("?") if tokens else ""
        if _RE_IDENT.match(candidate):
            names.append(candidate)
    return names


class SearchTruncated(RuntimeError):
    """The declaration search hit its file cap before answering.

    Its own exception type because the honest answer is "I stopped looking",
    which is `unchecked` — NOT "no declaration exists", which is what a silent
    `[:200]` slice used to report. Those are different facts, and reporting the
    second when the first is true is how a cap becomes a wrong answer.
    """


def _ts_files(repo_root: Path, scope: str, first: Path | None = None) -> list[Path]:
    files, truncated = _candidate_files(repo_root, scope)
    if truncated:
        # `_candidate_files` has its OWN cap, and discarding its flag reopened
        # the hole the MAX_DECL_FILES check was added to close: a checkout with
        # more than MAX_FILES_SCANNED files can truncate the walk while leaving
        # fewer than MAX_DECL_FILES TypeScript files behind, so the declaration
        # search would answer "not found" off a partial walk without ever
        # tripping its own cap.
        raise SearchTruncated(
            f"the directory walk stopped at the {MAX_FILES_SCANNED}-file cap, so "
            "the declaration search would run against a partial checkout"
        )
    out = [p for p in files if p.suffix in (".ts", ".tsx")]
    if first is not None:
        out = [first] + [p for p in out if p != first]
    if len(out) > MAX_DECL_FILES:
        raise SearchTruncated(
            f"the checkout has {len(out)} TypeScript files, over the "
            f"{MAX_DECL_FILES}-file declaration-search cap"
        )
    return out


def _return_type_members(ret: str, decl_file: Path, repo_root: Path, timeout: float) -> list[str] | None:
    """Members of a return type, whether it is named or written inline."""
    if ret.strip().startswith("{"):
        with tempfile.TemporaryDirectory() as td:
            snippet = Path(td) / "ret.ts"
            # `ret` came out of the CHECKOUT, not out of a claim. It is source we
            # just read, being handed back to the same parser that produced it.
            snippet.write_text(f"type __RPV2_RET = {ret};\n", encoding="utf-8")
            matches = _ast_grep_pattern(_TYPE_ALIAS_PATTERN, [snippet], timeout)
        return _members_from_body(matches[0]) if matches else None

    if not _RE_IDENT.match(ret.strip()):
        return None
    name = ret.strip()
    search = _ts_files(repo_root, "all", first=decl_file)
    for pattern in (_INTERFACE_PATTERN, _TYPE_ALIAS_PATTERN):
        for m in _ast_grep_pattern(pattern, search, timeout):
            if _single(m, "NAME") == name:
                return _members_from_body(m)
    return None


def _find_declaration(resolved: ResolvedInput, repo_root: Path, timeout: float) -> tuple[Path, str] | None:
    """Locate `name`'s declaration and return (file, declared return type)."""
    if resolved.path:
        candidates = [repo_root / resolved.path]
    else:
        candidates = _ts_files(repo_root, resolved.scope)
    leaf = resolved.name.rsplit(".", 1)[-1]
    for pattern in _DECL_PATTERNS:
        for m in _ast_grep_pattern(pattern, candidates, timeout):
            if _single(m, "NAME") == leaf:
                ret = _single(m, "RET")
                if ret:
                    return Path(m["file"]), ret
    return None


def _expected_members(expected: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9_$]+", expected) if t and _RE_IDENT.match(t)]


def _verify_typecheck(
    claim: Claim, resolved: ResolvedInput, repo_root: Path, *, timeout: float,
) -> Verdict:
    found = _find_declaration(resolved, repo_root, timeout)
    if found is None:
        return Verdict(UNVERIFIABLE,
                       f"no declaration of {resolved.name!r} with a return-type "
                       "annotation was found in the checkout")
    decl_file, ret = found

    if claim.kind == "predicate_result":
        # A TypeScript type predicate (`x is Foo`) is the only predicate whose
        # RESULT is settled by its declaration. Anything else — "does this
        # matcher match optional chaining?" — is a question about runtime
        # behaviour, and answering it means executing code. FR-024 says we do
        # not, so we say so rather than guessing.
        if " is " not in ret:
            return Verdict(UNVERIFIABLE,
                           f"{resolved.name!r} declares `{ret}`, which is not a type "
                           "predicate; settling its result requires execution (FR-024)")
        declared = ret.split(" is ", 1)[1].strip()
        wanted = _expected_members(claim.expected)
        if declared and wanted and declared not in wanted:
            return Verdict(REFUTED, f"declares the type predicate `{ret}`; "
                                    f"claim expected {claim.expected!r}")
        return Verdict(UNVERIFIABLE,
                       f"declares `{ret}`; the claim does not contradict it on its face")

    # return_shape
    members = _return_type_members(ret, decl_file, repo_root, timeout)
    if members is None:
        return Verdict(UNVERIFIABLE,
                       f"{resolved.name!r} returns {ret!r}, whose members could not be "
                       "resolved from a declaration")
    wanted = _expected_members(claim.expected)
    if not wanted:
        return Verdict(UNVERIFIABLE,
                       f"expected {claim.expected!r} names no fields to compare against "
                       f"the declared {{{', '.join(members)}}}")
    missing = [w for w in wanted if w not in members]
    observed = "{" + ", ".join(members) + "}"
    if missing:
        return Verdict(REFUTED,
                       f"{resolved.name} declares {ret} = {observed}; "
                       f"{', '.join(missing)} absent")
    return Verdict(CONFIRMED, f"{resolved.name} declares {ret} = {observed}")


# --- entry point -------------------------------------------------------------


def verify_claim(
    claim: Claim | None,
    repo_root: Path,
    *,
    rule_paths: dict[str, Path] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    log: Callable[[str], None] = _default_log,
) -> Verdict:
    """Resolve one claim. Never returns `confirmed` without an observation."""
    if claim is None:
        return Verdict(UNVERIFIABLE, "judgment finding: no checkable claim")

    rule_paths = rule_paths or {}
    method = claim.check.method

    if method == "execute":
        # T028 / FR-024. Loud on purpose: a deferred capability that reports
        # nothing is indistinguishable from one that shipped.
        log(f"[verify] execute is not implemented (FR-024); {claim.subject!r} "
            "resolves to unverifiable pending a sandboxing model")
        return Verdict(UNVERIFIABLE,
                       "the execute check method is deferred until a sandboxing model "
                       "is specified (FR-024); this claim was NOT checked")

    expected_method = method_for_kind(claim.kind)
    if expected_method is not None and expected_method != method:
        log(f"[verify] kind {claim.kind!r} routed to {method!r}, expected "
            f"{expected_method!r}; refusing to answer a different question")
        return Verdict(UNVERIFIABLE,
                       f"kind {claim.kind!r} is answerable by {expected_method}, "
                       f"not by {method}")

    try:
        resolved = resolve_input(claim.check, repo_root, rule_ids=frozenset(rule_paths))
    except InputRejected as e:
        # Not a crash — a refusal, and one worth seeing. A claim whose input
        # fails the allowlist is either a malformed reviewer response or an
        # attempt to steer verification into executing something.
        log(f"[verify] SECURITY: rejected check.input for {claim.subject!r}: {e}")
        return Verdict(UNCHECKED, f"verification input rejected by the allowlist: {e}")

    if method == "enumerate" and resolved.form == "rule" and shutil.which("ast-grep") is None:
        return Verdict(UNCHECKED, "ast-grep is not installed, so the rule could not run")
    if method == "typecheck" and shutil.which("ast-grep") is None:
        return Verdict(UNCHECKED, "ast-grep is not installed, so no declaration could be read")

    try:
        if method == "enumerate":
            return _verify_enumerate(
                claim, resolved, repo_root, rule_paths=rule_paths, timeout=timeout,
            )
        if method == "typecheck":
            return _verify_typecheck(claim, resolved, repo_root, timeout=timeout)
        return Verdict(UNVERIFIABLE, f"unknown check method {method!r}")
    except subprocess.TimeoutExpired:
        # T031. Every one of these three is `unchecked`, which RENDERS the
        # finding with a marker. The alternative — treating a crashed verifier
        # as a clean bill of health — is the exact shape of every silent
        # degradation this spec was written for.
        log(f"[verify] TIMEOUT after {timeout}s verifying {claim.subject!r}")
        return Verdict(UNCHECKED, f"verification timed out after {timeout}s")
    except SearchTruncated as e:
        # A reported cap, never a silent one. The alternative — answering
        # "no declaration found" after stopping early — turns a resource limit
        # into a wrong factual claim about the checkout.
        log(f"[verify] SEARCH CAPPED verifying {claim.subject!r}: {e}")
        return Verdict(UNCHECKED, f"stopped looking before answering: {e}")
    except (OSError, RuntimeError, json.JSONDecodeError) as e:
        log(f"[verify] FAILED verifying {claim.subject!r}: {type(e).__name__}: {e}")
        return Verdict(UNCHECKED, f"verification failed: {type(e).__name__}: {e}")
    except Exception as e:
        # Deliberate blind backstop, and the breadth is the point: the three
        # handlers above name what is expected, and anything unexpected must
        # still land as `unchecked` rather than propagate and abort the run.
        # (This rationale used to ride on a BLE001 suppression directive. BLE001
        # is not in the select set, so that directive suppressed nothing — a
        # comment claiming a rule was considered here when it was never on.
        # RUF100 removed it; the reasoning was worth keeping, the false claim
        # was not. Spelled out in prose rather than quoted, because ruff reads
        # the token anywhere in a comment and quoting it here re-creates the
        # very thing being described, as an "invalid directive" warning.)
        log(f"[verify] UNEXPECTED {type(e).__name__} verifying {claim.subject!r}: {e}")
        return Verdict(UNCHECKED, f"verification raised {type(e).__name__}")
