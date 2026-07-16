"""Autoregressive output generation helpers for Amosclaud model services.

The production web server stays API-decoupled. A configured PyTorch model
service may import these helpers to project hidden states to vocabulary logits,
apply temperature, perform top-p sampling, decode BPE token IDs, evaluate stop
sequences, and reuse a model's key-value cache.
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
    stop_sequences: tuple[str, ...] = ("```",)
    use_kv_cache: bool = True

    def validate(self) -> None:
        if self.temperature <= 0:
            raise ValueError("temperature must be greater than zero")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in the interval (0, 1]")
        if self.max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be greater than zero")


class LanguageModelHead(nn.Module):
    """Project final hidden vectors into unnormalized vocabulary logits."""

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


def should_stop(token_id: Tensor, decoded_text: str, config: GenerationConfig) -> bool:
    """Return true when EOS or a configured structural stop sequence appears."""
    if config.eos_token_id is not None and torch.all(token_id == config.eos_token_id):
        return True
    return any(sequence and sequence in decoded_text for sequence in config.stop_sequences)


@torch.inference_mode()
def generate_tokens(model, tokenizer, prompt: str, config: GenerationConfig | None = None) -> str:
    """Generate readable text one token at a time with optional KV caching.

    The model must accept ``input_ids`` and should accept ``past_key_values`` and
    ``use_cache`` when KV caching is enabled. Its output must expose ``logits``;
    cache-compatible outputs may also expose ``past_key_values``.
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
    model_input = input_ids
    past_key_values = None
    decoded = tokenizer.decode(generated[0], skip_special_tokens=True)

    for _ in range(cfg.max_new_tokens):
        kwargs = {"input_ids": model_input}
        if cfg.use_kv_cache:
            kwargs["use_cache"] = True
            if past_key_values is not None:
                kwargs["past_key_values"] = past_key_values

        output = model(**kwargs)
        next_logits = output.logits[:, -1, :]
        next_token = top_p_sample(next_logits, temperature=cfg.temperature, top_p=cfg.top_p)
        generated = torch.cat([generated, next_token], dim=-1)
        decoded = tokenizer.decode(generated[0], skip_special_tokens=True)

        if should_stop(next_token, decoded, cfg):
            break

        past_key_values = getattr(output, "past_key_values", None) if cfg.use_kv_cache else None
        model_input = next_token if past_key_values is not None else generated

    return decoded
