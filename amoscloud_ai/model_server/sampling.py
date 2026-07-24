"""Greedy, top-k, and top-p token sampling."""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor
import torch.nn.functional as F


@dataclass(frozen=True)
class SamplingConfig:
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int | None = None
    do_sample: bool = True

    def validate(self) -> None:
        if self.temperature <= 0:
            raise ValueError("temperature must be greater than zero")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if self.top_k is not None and self.top_k <= 0:
            raise ValueError("top_k must be positive")


def filter_logits(logits: Tensor, config: SamplingConfig) -> Tensor:
    config.validate()
    filtered = logits / config.temperature

    if config.top_k is not None:
        k = min(config.top_k, filtered.size(-1))
        threshold = torch.topk(filtered, k, dim=-1).values[..., -1, None]
        filtered = filtered.masked_fill(
            filtered < threshold,
            float("-inf"),
        )

    if config.top_p < 1:
        sorted_logits, sorted_indices = torch.sort(
            filtered,
            descending=True,
            dim=-1,
        )
        cumulative = torch.cumsum(
            F.softmax(sorted_logits, dim=-1),
            dim=-1,
        )
        remove = cumulative > config.top_p
        remove[..., 1:] = remove[..., :-1].clone()
        remove[..., 0] = False
        sorted_logits = sorted_logits.masked_fill(remove, float("-inf"))
        restored = torch.full_like(filtered, float("-inf"))
        filtered = restored.scatter(-1, sorted_indices, sorted_logits)

    return filtered


def sample_next_token(
    logits: Tensor,
    config: SamplingConfig | None = None,
    generator: torch.Generator | None = None,
) -> Tensor:
    cfg = config or SamplingConfig()
    filtered = filter_logits(logits, cfg)
    if not cfg.do_sample:
        return torch.argmax(filtered, dim=-1, keepdim=True)
    probabilities = F.softmax(filtered, dim=-1)
    return torch.multinomial(
        probabilities,
        num_samples=1,
        generator=generator,
    )
