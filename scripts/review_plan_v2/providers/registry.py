"""Provider tag -> module, and which tags may run which stage.

One place that knows the provider set. Before this module the broad-pass provider
was hardcoded in four reviewer factories and again as a bare `"deepseek"` string
in three orchestrator dicts, so "use a different broad provider" was a
seven-site edit and the pricing lookup silently kept charging DeepSeek rates.

Three rules are encoded here rather than left to configuration:

1. **Anthropic cannot review.** The operator implements with Claude Code, so a
   Claude judge on Claude-written code is the anti-self-grading violation this
   whole design exists to avoid. The module stays importable for historical
   replay tooling that needs to compute Anthropic cost, but it is not selectable
   as a reviewer.
2. **DeepSeek cannot review either, and this is why the default moved.** The
   broad pass ships the diff of every changed file to its provider. DeepSeek's
   API is operated from the PRC, and some of the repositories reviewed with this
   tool are employer repositories under a data-egress expectation. Making that a
   per-repo opt-out failed open in two ways at once: a repo that simply forgot
   `.review-plan-v2.yaml` got DeepSeek, and — worse — a repo that *did* declare
   another provider still got DeepSeek on any machine without `yq`, because the
   YAML loader bails before reading the key and the default applied. A default
   that is wrong only when a parser is missing is a default that is wrong.
   Removing the tag entirely is what makes those failure modes unrepresentable
   rather than merely discouraged.
3. **A cascade leg on the same provider as the broad pass is not a second
   opinion.** The cascade's value is N *independent* perspectives on high-risk
   paths. Running the `google` tag as both broad pass and cascade leg is one
   perspective billed twice, so the orchestrator drops the duplicate leg and
   says so. (The tag is `google`, not `gemini`. Gemini is the model family it
   serves; every tag in this module is the provider, and mixing the two is how
   GEMINI_API_BASE ended up in an allowlist that nothing reads.)

The modules for refused providers stay importable on purpose: ALL_TAGS still
keys the counter dicts, the pricing table, and telemetry, so historical
calls.jsonl from before this change still costs out correctly.
"""
from __future__ import annotations

import os

from . import anthropic, deepseek, google, openai

# Every tag the counters, pricing table, and telemetry know about.
ALL_TAGS: tuple[str, ...] = ("deepseek", "openai", "google", "anthropic")

# Tags selectable as a reviewer. Anthropic and DeepSeek are deliberately absent;
# see the module docstring. Ordered by cost-per-token ascending, because the
# broad pass runs on every file in the diff and the cascade runs on a small
# subset, so this is the order an operator picking a broad provider should
# consider them in.
REVIEW_CAPABLE: tuple[str, ...] = ("google", "openai")

# The broad-pass default. Named here rather than repeated as a literal in
# RunConfig, four reviewer factories, and the pricing fallback: those five copies
# are how the old "deepseek" default outlived every decision to move off it.
DEFAULT_BROAD: str = "google"

# Tags that are known but refused, mapped to the reason. The reason is the point
# — both of these look like they should work, and a bare "unknown provider"
# reads as an unimplemented feature rather than a decision.
REFUSED: dict[str, str] = {
    "anthropic": (
        "anthropic is not selectable as a reviewer: the implementation model here is "
        "Claude, so a Claude reviewer is self-grading"
    ),
    "deepseek": (
        "deepseek is no longer selectable: the broad pass sends the diff of every "
        "changed file to its provider, and this tool reviews employer repositories "
        "under a data-egress expectation that the PRC-operated DeepSeek API does not "
        "meet. It was removed rather than defaulted-away because a per-repo opt-out "
        "failed open on any machine without yq"
    ),
}

_MODULES = {
    "deepseek": deepseek,
    "openai": openai,
    "google": google,
    "anthropic": anthropic,
}

# Env vars that carry each provider's key, in the order the provider itself
# checks them. Kept beside the modules so a preflight can report a missing key
# by name instead of letting every call fail `auth (HTTP no-response)` — the
# failure mode that cost a full diagnostic session when the real cause was
# egress filtering rather than a bad key.
KEY_ENV: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

# The base-URL override each provider module reads, by tag. One entry per module,
# spelled exactly as that module spells it. All four currently happen to be
# TAG.upper() + "_API_BASE"; they are written out anyway, because the value that has
# to match is whatever the module reads, not whatever the tag derives to, and the day
# those diverge a derived name would be wrong silently.
#
# The asymmetry to watch is on the KEY side, not here: google's key vars are
# GEMINI_API_KEY / GOOGLE_API_KEY, so the tag does not determine the key name. Two
# reviewers read an earlier version of this comment as saying google's *base* was the
# odd one out and proposed "fixing" it to GEMINI_API_BASE. Do not. google.py reads
# GOOGLE_API_BASE, nothing reads GEMINI_API_BASE, and the tool's own allowlist named
# GEMINI_API_BASE until 2026-08-25 — which is the bug, not the fix. Getting this name
# wrong does not raise: the override is simply never seen and the request goes to the
# real Gemini endpoint instead of the test fixture. That already shipped once.
#
# This exists so the harness can point every provider at a fixture server by
# iterating the registry rather than by repeating a literal tuple. A provider added
# here and forgotten there is skipped for want of a base URL, and a skipped provider
# makes its own tests pass by not running.
BASE_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_BASE",
    "openai": "OPENAI_API_BASE",
    "google": "GOOGLE_API_BASE",
    "anthropic": "ANTHROPIC_API_BASE",
}

# Drift guard. The harness indexes BASE_ENV and KEY_ENV by every tag in ALL_TAGS, so a
# tag added above but missed in either dict is a KeyError inside a test-support module,
# surfacing as an unrelated-looking test error. Assert it at import instead, where the
# message names the actual problem. Deliberately not a .get() with a skip at the call
# site: a provider silently skipped for want of a base URL is the fail-open shape this
# registry exists to remove — it would talk to the real endpoint instead of the fixture.
for _dict_name, _d in (("KEY_ENV", KEY_ENV), ("BASE_ENV", BASE_ENV)):
    _missing = set(ALL_TAGS) - set(_d)
    _extra = set(_d) - set(ALL_TAGS)
    if _missing or _extra:  # pragma: no cover - import-time invariant
        raise RuntimeError(
            f"provider registry drift: {_dict_name} does not cover ALL_TAGS "
            f"(missing={sorted(_missing)}, unexpected={sorted(_extra)})"
        )

# Same guard, for the attribute `default_model()` reaches by getattr. A module that
# drifts or forgets DEFAULT_MODEL raises AttributeError deep inside a reviewer's
# construction, naming the getattr rather than the module that is actually wrong.
# Asserted here for the same reason as the dicts above, and covering _MODULES rather
# than REVIEW_TAGS on purpose: the refused providers keep their modules for pricing
# and telemetry replay, so their metadata has to stay well-formed too.
_no_default = sorted(t for t, m in _MODULES.items() if not getattr(m, "DEFAULT_MODEL", None))
if _no_default:  # pragma: no cover - import-time invariant
    raise RuntimeError(
        f"provider registry drift: no usable DEFAULT_MODEL on {_no_default} — "
        f"default_model() reads it by getattr and would fail at call time instead"
    )

# KEY_ENV values must be tuples, not bare strings, and this is not pedantry. Callers
# iterate them — `for var in KEY_ENV[tag]` — so a value written as "DEEPSEEK_API_KEY"
# instead of ("DEEPSEEK_API_KEY",) iterates CHARACTERS. The test harness would then set
# env["D"], env["E"], env["P"]… and never the actual key, the provider would read as
# having no key, and its tests would pass by not running. A reviewer flagged the call
# site; the invariant belongs here, because every current and future caller iterating
# this dict depends on it and only one of them would be guarded otherwise.
for _tag, _names in KEY_ENV.items():
    if not isinstance(_names, tuple) or not all(isinstance(n, str) for n in _names):
        raise RuntimeError(  # pragma: no cover - import-time invariant
            f"KEY_ENV[{_tag!r}] must be a tuple of str, got {_names!r}. A bare string "
            f"iterates as characters and silently leaves the real key unset."
        )

# BASE_ENV values must be non-empty strings, for the symmetric reason. The drift guard
# above only proves the KEYS cover ALL_TAGS, so an entry written as `"mistral": None`
# passes it and then the harness does `env[registry.BASE_ENV[tag]] = base_url` —
# `env[None] = ...`, which raises inside subprocess with a message about environment
# keys rather than about this dict. A reviewer reached the same call site from the other
# direction and proposed a `.get()` with a truthiness check there; that would be the
# fail-open version, because a provider silently skipped for want of a base URL talks to
# the real endpoint instead of the fixture. Guard the invariant here, once, instead.
for _tag, _var in BASE_ENV.items():
    if not isinstance(_var, str) or not _var:
        raise RuntimeError(  # pragma: no cover - import-time invariant
            f"BASE_ENV[{_tag!r}] must be a non-empty str, got {_var!r}. Callers use it "
            f"directly as an environment variable name, where a non-str raises far from "
            f"here and an empty str would set a nameless variable."
        )
# `module()` gates on REFUSED rather than on REVIEW_CAPABLE, so "known and not
# refused" is what actually makes a tag selectable. That is one decision expressed
# in two places, and the two can disagree: a provider added to _MODULES/ALL_TAGS for
# pricing or telemetry replay — which is exactly why deepseek and anthropic are still
# in there — becomes selectable by accident unless someone also remembers to refuse
# it. Assert the two agree at import, where the message names the omission, instead
# of discovering it as a diff shipped to a provider nobody chose.
_selectable = set(_MODULES) - set(REFUSED)
if _selectable != set(REVIEW_CAPABLE):  # pragma: no cover - import-time invariant
    raise RuntimeError(
        "provider registry drift: _MODULES - REFUSED is "
        f"{sorted(_selectable)} but REVIEW_CAPABLE is {sorted(REVIEW_CAPABLE)}. "
        "A tag added for pricing or replay must also be listed in REFUSED with a "
        "reason, or it is silently selectable as a reviewer."
    )

del _dict_name, _d, _missing, _extra, _tag, _names, _var, _selectable


class UnknownProvider(ValueError):
    """A configured provider tag is not one this build can review with."""


def module(tag: str):
    """Return the provider module for a review-capable tag.

    Raises UnknownProvider for an unknown tag, and for a REFUSED tag with the
    specific reason, since those look like they should work.
    """
    if tag in REFUSED:
        raise UnknownProvider(
            REFUSED[tag] + ". Choose one of: " + ", ".join(REVIEW_CAPABLE)
        )
    if tag not in _MODULES:
        raise UnknownProvider(
            f"unknown provider {tag!r}. Choose one of: " + ", ".join(REVIEW_CAPABLE)
        )
    return _MODULES[tag]


def default_model(tag: str) -> str:
    return module(tag).DEFAULT_MODEL


def key_var(tag: str) -> str | None:
    """The first env var actually carrying a key for this provider, or None.

    Stripped before the truthiness test. `GEMINI_API_KEY=" "` — a trailing
    continuation in a .env, or a shell `export K="$UNSET_VAR "` — is truthy as a
    string, so it counted as a key: the preflight reported the leg operable, then
    every one of that leg's calls came back `auth (HTTP 401)` and the run
    reported a provider fault. That is the same shape as the empty-string case
    the falsy check already handles, and the empty case is the one that happens
    to be caught by accident. A missing key is diagnosable in one line; a
    whitespace key spends a review's worth of calls to say the same thing.
    """
    for var in KEY_ENV.get(tag, ()):
        if (os.environ.get(var) or "").strip():
            return var
    return None


def has_key(tag: str) -> bool:
    return key_var(tag) is not None


def missing_key_hint(tag: str) -> str:
    """Human-facing description of which env var(s) would supply the key."""
    names = KEY_ENV.get(tag, ())
    if not names:
        return f"{tag} (no key env var known)"
    return f"{tag} (set {' or '.join(names)})"
