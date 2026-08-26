from __future__ import annotations

from ..providers import registry
from .base import Reviewer


def make(provider: str | None = None, model: str | None = None) -> Reviewer:
    """Build the security reviewer.

    `provider` is the broad-pass provider tag. None means registry.DEFAULT_BROAD;
    the default is resolved there rather than written as a literal here, because
    four copies of a literal default is how the old DeepSeek default outlived the
    decision to move off it. `model` defaults to that provider's frontier tier.

    `provider` is first positionally, and a caller who means `model` and forgets
    the keyword gets a loud failure rather than a wrong reviewer: a model name is
    not a provider tag, so registry.module() raises UnknownProvider naming the
    capable tags. Keyword-only arguments would make that a TypeError instead,
    which is not an improvement worth churning eight callsites for.
    """
    prov = registry.module(provider or registry.DEFAULT_BROAD)
    return Reviewer(
        name="security", prompt_filename="security.md",
        provider_call=prov.call, model=model or prov.DEFAULT_MODEL,
        needs_manifest=True,
    )
