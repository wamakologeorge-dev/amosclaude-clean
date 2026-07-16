"""Autoregressive output generation helpers for Amosclaud model services.

The production web server stays API-decoupled. A configured PyTorch model
service may import these helpers to project hidden states to vocabulary logits,
apply temperature, perform top-p sampling, and decode generated token IDs.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn
import torch.nn.functional as F


@dataclass(frozen=True)
class GenerationConfig:
    temperature: float = 0.8
    top_p: float = 0.95
    max_new_tokens: int = 256
    eos_token_id: int | None = None

    def validate(self) -> None:
        if self.temperature <= 0:
            raise ValueError("temperature must be greater than zero")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in the interval (0, 1]")
        if self.max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be greater than zero")


class LanguageModelHead(nn.Module):
    """Project final hidden vectors into vocabulary logits."""

    def __init__(self, d_model: int, vocab_size: int, bias: bool = False) -> None:
        super().__init__()
        if d_model <= 0 or vocab_size <= 0:
            raise ValueError("d_model and vocab_size must be greater than zero")
        self.projection = nn.Linear(d_model, vocab_size, bias=bias)

    def forward(self, hidden_states: Tensor) -> Tensor:
        return self.projection(hidden_states)


def top_p_sample(logits: Tensor, *, temperature: float = 0.8, top_p: float = 0.95) -> Tensor:
    """Sample one token ID per batch using temperature and nucleus sampling."""
    if temperature <= 0:
        raise ValueError("temperature must be greater than zero")
    if not 0 < top_p <= 1:
        raise ValueError("top_p must be in the interval (0, 1]")

    scaled = logits / temperature
    sorted_logits, sorted_indices = torch.sort(scaled, descending=True, dim=-1)
    sorted_probs = F.softmax(sorted_logits, dim=-1)
    cumulative = torch.cumsum(sorted_probs, dim=-1)

    remove = cumulative > top_p
    remove[..., 1:] = remove[..., :-1].clone()
    remove[..., 0] = False
    sorted_logits = sorted_logits.masked_fill(remove, float("-inf"))

    filtered_probs = F.softmax(sorted_logits, dim=-1)
    sampled_sorted_index = torch.multinomial(filtered_probs, num_samples=1)
    return torch.gather(sorted_indices, dim=-1, index=sampled_sorted_index)


@torch.inference_mode()
def generate_tokens(model, tokenizer, prompt: str, config: GenerationConfig | None = None) -> str:
    """Generate readable text one token at a time from a compatible causal model.

    The model must accept ``input_ids`` and return an object with ``logits``.
    The tokenizer must provide ``encode`` and ``decode`` methods.
    """
    cfg = config or GenerationConfig()
    cfg.validate()

    input_ids = tokenizer.encode(prompt, return_tensors="pt")
    try:
        device = next(model.parameters()).device
        input_ids = input_ids.to(device)
    except StopIteration:
        pass

    generated = input_ids
    for _ in range(cfg.max_new_tokens):
        output = model(input_ids=generated)
        next_logits = output.logits[:, -1, :]
        next_token = top_p_sample(next_logits, temperature=cfg.temperature, top_p=cfg.top_p)
        generated = torch.cat([generated, next_token], dim=-1)
        if cfg.eos_token_id is not None and torch.all(next_token == cfg.eos_token_id):
            break

    return tokenizer.decode(generated[0], skip_special_tokens=True)
