"""Shared context types. Separate module so `related` and `standing` can both
import it without either depending on the other."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBlock:
    origin: str   # standing | same-file | imported
    path: str     # repo-relative
    symbol: str   # declared name, or the file's own name for standing files
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)
