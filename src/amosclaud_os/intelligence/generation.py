"""Output-generation utilities for Amosclaud model services.

These helpers implement the LM-head, temperature scaling, top-p filtering,
and token sampling stages described by the Transformer generation pipeline.
They are tools used under the canonical Amosclaud Autonomous kernel; they do
not create an independent agent or model brain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class TokenizerProtocol(Protocol):
    eos_token_id: int | None

    def decode(self, token_ids: list[int]) -> str: ...


@dataclass(frozen=True)
class GenerationStep:
    token_id: int
    text: str
    probability: float


class LanguageModelHead(nn.Module):
    """Project hidden vectors from ``d_model`` into vocabulary logits."""

    def __init__(self, d_model: int, vocab_size: int, bias: bool = False) -> None:
        super().__init__()
        if d_model <= 0 or vocab_size <= 0:
            raise ValueError("d_model and vocab_size must be greater than zero")
        self.projection = nn.Linear(d_model, vocab_size, bias=bias)

    def forward(self, hidden_states: Tensor) -> Tensor:
        if hidden_states.ndim != 3:
            raise ValueError("hidden_states must have shape [batch, sequence, d_model]")
        return self.projection(hidden_states)


def temperature_softmax(logits: Tensor, temperature: float = 1.0) -> Tensor:
    """Convert logits into probabilities using a positive temperature."""
    if temperature <= 0:
        raise ValueError("temperature must be greater than zero")
    return F.softmax(logits / temperature, dim=-1)


def top_p_filter(logits: Tensor, top_p: float = 0.9) -> Tensor:
    """Apply nucleus filtering while preserving at least one token."""
    if not 0.0 < top_p <= 1.0:
        raise ValueError("top_p must be in the range (0, 1]")
    if top_p == 1.0:
        return logits

    sorted_logits, sorted_indices = torch.sort(logits, descending=True, dim=-1)
    sorted_probs = F.softmax(sorted_logits, dim=-1)
    cumulative = torch.cumsum(sorted_probs, dim=-1)

    remove = cumulative > top_p
    remove[..., 1:] = remove[..., :-1].clone()
    remove[..., 0] = False

    filtered_sorted = sorted_logits.masked_fill(remove, torch.finfo(logits.dtype).min)
    filtered = torch.full_like(logits, torch.finfo(logits.dtype).min)
    return filtered.scatter(-1, sorted_indices, filtered_sorted)


def sample_next_token(
    logits: Tensor,
    *,
    temperature: float = 1.0,
    top_p: float = 0.9,
    generator: torch.Generator | None = None,
) -> tuple[Tensor, Tensor]:
    """Sample one token per batch from the final sequence position."""
    if logits.ndim not in {2, 3}:
        raise ValueError("logits must have shape [batch, vocab] or [batch, sequence, vocab]")
    next_logits = logits[:, -1, :] if logits.ndim == 3 else logits
    scaled = next_logits / temperature if temperature > 0 else None
    if scaled is None:
        raise ValueError("temperature must be greater than zero")
    filtered = top_p_filter(scaled, top_p=top_p)
    probabilities = F.softmax(filtered, dim=-1)
    token_ids = torch.multinomial(probabilities, num_samples=1, generator=generator)
    selected = probabilities.gather(-1, token_ids)
    return token_ids, selected


def decode_step(tokenizer: TokenizerProtocol, token_id: Tensor, probability: Tensor) -> GenerationStep:
    """Decode a single sampled token into a structured, reportable result."""
    numeric_id = int(token_id.reshape(-1)[0].item())
    return GenerationStep(
        token_id=numeric_id,
        text=tokenizer.decode([numeric_id]),
        probability=float(probability.reshape(-1)[0].item()),
    )
