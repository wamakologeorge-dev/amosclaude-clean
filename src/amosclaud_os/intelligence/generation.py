"""Output-generation utilities for Amosclaud model services.

These helpers implement the LM-head, temperature scaling, top-p filtering,
token decoding, stop evaluation, and cache-aware auto-regressive generation.
They are tools used under the canonical Amosclaud Autonomous kernel; they do
not create an independent agent or model brain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class TokenizerProtocol(Protocol):
    eos_token_id: int | None

    def decode(self, token_ids: list[int]) -> str: ...


class CacheAwareModelProtocol(Protocol):
    def __call__(
        self,
        input_ids: Tensor,
        *,
        past_key_values: Any | None = None,
        use_cache: bool = True,
    ) -> Any: ...


@dataclass(frozen=True)
class GenerationStep:
    token_id: int
    text: str
    probability: float


@dataclass(frozen=True)
class GenerationResult:
    token_ids: tuple[int, ...]
    text: str
    stop_reason: str
    steps: tuple[GenerationStep, ...]


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
    if temperature <= 0:
        raise ValueError("temperature must be greater than zero")
    next_logits = logits[:, -1, :] if logits.ndim == 3 else logits
    filtered = top_p_filter(next_logits / temperature, top_p=top_p)
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


def decode_token_stream(tokenizer: TokenizerProtocol, token_ids: Sequence[int]) -> str:
    """Reconstruct readable text from a complete token stream."""
    return tokenizer.decode([int(token_id) for token_id in token_ids])


def evaluate_stop(
    *,
    token_id: int,
    generated_text: str,
    eos_token_id: int | None,
    stop_sequences: Sequence[str] = (),
) -> str | None:
    """Return a truthful stop reason or ``None`` when generation should continue."""
    if eos_token_id is not None and token_id == eos_token_id:
        return "eos_token"
    for sequence in stop_sequences:
        if sequence and sequence in generated_text:
            return f"stop_sequence:{sequence}"
    return None


def generate_autoregressive(
    model: CacheAwareModelProtocol,
    tokenizer: TokenizerProtocol,
    input_ids: Tensor,
    *,
    max_new_tokens: int = 128,
    temperature: float = 1.0,
    top_p: float = 0.9,
    stop_sequences: Sequence[str] = ("```",),
    generator: torch.Generator | None = None,
) -> GenerationResult:
    """Generate tokens one at a time while reusing the model KV cache.

    The first pass receives the full prompt. Later passes receive only the
    newest token together with ``past_key_values``. The result always reports
    why the loop ended, preventing silent or infinite generation.
    """
    if input_ids.ndim != 2 or input_ids.size(0) != 1:
        raise ValueError("input_ids must have shape [1, sequence]")
    if max_new_tokens <= 0:
        raise ValueError("max_new_tokens must be greater than zero")

    current_input = input_ids
    cache: Any | None = None
    generated_ids: list[int] = []
    steps: list[GenerationStep] = []
    stop_reason = "max_new_tokens"

    for _ in range(max_new_tokens):
        outputs = model(current_input, past_key_values=cache, use_cache=True)
        logits = outputs.logits
        cache = getattr(outputs, "past_key_values", None)
        next_token, probability = sample_next_token(
            logits,
            temperature=temperature,
            top_p=top_p,
            generator=generator,
        )
        step = decode_step(tokenizer, next_token, probability)
        generated_ids.append(step.token_id)
        steps.append(step)
        generated_text = decode_token_stream(tokenizer, generated_ids)

        reason = evaluate_stop(
            token_id=step.token_id,
            generated_text=generated_text,
            eos_token_id=tokenizer.eos_token_id,
            stop_sequences=stop_sequences,
        )
        if reason:
            stop_reason = reason
            break

        current_input = next_token.to(device=input_ids.device, dtype=input_ids.dtype)

    return GenerationResult(
        token_ids=tuple(generated_ids),
        text=decode_token_stream(tokenizer, generated_ids),
        stop_reason=stop_reason,
        steps=tuple(steps),
    )
