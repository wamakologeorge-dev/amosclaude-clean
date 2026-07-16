"""Reusable intelligence components governed by the Amosclaud Autonomous kernel."""

from .attention import ScaledDotProductAttention
from .generation import (
    GenerationResult,
    GenerationStep,
    LanguageModelHead,
    decode_step,
    decode_token_stream,
    evaluate_stop,
    generate_autoregressive,
    sample_next_token,
    temperature_softmax,
    top_p_filter,
)

__all__ = [
    "ScaledDotProductAttention",
    "GenerationResult",
    "GenerationStep",
    "LanguageModelHead",
    "decode_step",
    "decode_token_stream",
    "evaluate_stop",
    "generate_autoregressive",
    "sample_next_token",
    "temperature_softmax",
    "top_p_filter",
]
