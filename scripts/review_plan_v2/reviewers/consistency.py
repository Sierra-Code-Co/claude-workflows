from ..providers import deepseek
from .base import Reviewer


def make(model: str = deepseek.DEFAULT_MODEL) -> Reviewer:
    return Reviewer(
        name="consistency", prompt_filename="consistency.md",
        provider_call=deepseek.call, model=model, needs_manifest=True,
    )
