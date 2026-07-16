"""Context-window accounting and truncation policies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ContextWindow:
    max_tokens: int
    reserve_output_tokens: int = 256

    def __post_init__(self) -> None:
        if self.max_tokens <= 0 or self.reserve_output_tokens < 0:
            raise ValueError("invalid context-window configuration")
        if self.reserve_output_tokens >= self.max_tokens:
            raise ValueError("reserve_output_tokens must be smaller than max_tokens")

    @property
    def input_budget(self) -> int:
        return self.max_tokens - self.reserve_output_tokens

    def trim_token_ids(self, token_ids: Sequence[int], *, keep_prefix: int = 0) -> list[int]:
        ids = list(token_ids)
        if len(ids) <= self.input_budget:
            return ids
        keep_prefix = max(0, min(keep_prefix, self.input_budget))
        tail_budget = self.input_budget - keep_prefix
        return ids[:keep_prefix] + ids[-tail_budget:] if tail_budget else ids[:keep_prefix]

    def usage(self, input_tokens: int, output_tokens: int = 0) -> dict[str, int | float]:
        total = input_tokens + output_tokens
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "remaining_tokens": max(0, self.max_tokens - total),
            "utilization": min(1.0, total / self.max_tokens),
        }
