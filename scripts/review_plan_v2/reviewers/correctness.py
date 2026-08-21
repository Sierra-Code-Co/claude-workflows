from ..providers import deepseek
from .base import Reviewer


def make(model: str = deepseek.DEFAULT_MODEL) -> Reviewer:
    return Reviewer(
        name="correctness", prompt_filename="correctness.md",
        provider_call=deepseek.call, model=model, needs_manifest=True,
    )
