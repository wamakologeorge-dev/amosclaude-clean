"""Autoregressive output generation helpers for Amosclaud model services."""

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


class LanguageModelHead(nn.Module):
    def __init__(self, d_model: int, vocab_size: int, bias: bool = False) -> None:
        super().__init__()
        if d_model <= 0 or vocab_size <= 0:
            raise ValueError("d_model and vocab_size must be greater than zero")
        self.projection = nn.Linear(d_model, vocab_size, bias=bias)

    def forward(self, hidden_states: Tensor) -> Tensor:
        return self.projection(hidden_states)


def apply_kv_cache(new_k: Tensor, new_v: Tensor, past_kv_cache=None):
    """Append newest K/V tensors along the sequence axis."""
    if past_kv_cache is None:
        return new_k, new_v
    past_k, past_v = past_kv_cache
    return torch.cat([past_k, new_k], dim=2), torch.cat([past_v, new_v], dim=2)


def top_p_sample(logits: Tensor, temperature: float = 0.8, top_p: float = 0.95) -> Tensor:
    if temperature <= 0 or not 0 < top_p <= 1:
        raise ValueError("temperature must be positive and top_p must be in (0, 1]")
    sorted_logits, sorted_indices = torch.sort(logits / temperature, descending=True, dim=-1)
    cumulative = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
    remove = cumulative > top_p
    remove[..., 1:] = remove[..., :-1].clone()
    remove[..., 0] = False
    sorted_logits = sorted_logits.masked_fill(remove, float("-inf"))
    sampled = torch.multinomial(F.softmax(sorted_logits, dim=-1), num_samples=1)
    return torch.gather(sorted_indices, dim=-1, index=sampled)


def should_stop(token_id: Tensor, decoded_text: str, config: GenerationConfig) -> bool:
    if config.eos_token_id is not None and torch.all(token_id == config.eos_token_id):
        return True
    return any(sequence and sequence in decoded_text for sequence in config.stop_sequences)


@torch.inference_mode()
def generate_tokens(model, tokenizer, prompt: str, config: GenerationConfig | None = None) -> str:
    cfg = config or GenerationConfig()
    if cfg.max_new_tokens <= 0:
        raise ValueError("max_new_tokens must be greater than zero")
    generated = tokenizer.encode(prompt, return_tensors="pt")
    try:
        generated = generated.to(next(model.parameters()).device)
    except StopIteration:
        pass
    model_input = generated
    past_key_values = None
    decoded = tokenizer.decode(generated[0], skip_special_tokens=True)
    for _ in range(cfg.max_new_tokens):
        kwargs = {"input_ids": model_input}
        if cfg.use_kv_cache:
            kwargs["use_cache"] = True
            if past_key_values is not None:
                kwargs["past_key_values"] = past_key_values
        output = model(**kwargs)
        next_token = top_p_sample(output.logits[:, -1, :], cfg.temperature, cfg.top_p)
        generated = torch.cat([generated, next_token], dim=-1)
        decoded = tokenizer.decode(generated[0], skip_special_tokens=True)
        if should_stop(next_token, decoded, cfg):
            break
        past_key_values = getattr(output, "past_key_values", None) if cfg.use_kv_cache else None
        model_input = next_token if past_key_values is not None else generated
    return decoded
