"""Composable causal transformer stack for Amosclaud model services."""
from __future__ import annotations

from dataclasses import dataclass
from torch import Tensor, nn

from .embeddings import TokenEmbeddings
from .kv_cache import KVCache
from .positional_encoding import SinusoidalPositionalEncoding
from .transformer_block import TransformerBlock


@dataclass(frozen=True)
class TransformerConfig:
    vocab_size: int
    d_model: int = 512
    num_heads: int = 8
    num_layers: int = 8
    hidden_size: int | None = None
    max_length: int = 8192
    dropout: float = 0.0

    def validate(self) -> None:
        if min(self.vocab_size, self.d_model, self.num_heads, self.num_layers, self.max_length) <= 0:
            raise ValueError("all transformer dimensions must be greater than zero")
        if self.d_model % self.num_heads:
            raise ValueError("d_model must be divisible by num_heads")


class TransformerStack(nn.Module):
    def __init__(self, config: TransformerConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.embeddings = TokenEmbeddings(config.vocab_size, config.d_model)
        self.positions = SinusoidalPositionalEncoding(config.d_model, config.max_length, config.dropout)
        self.layers = nn.ModuleList([
            TransformerBlock(config.d_model, config.num_heads, config.hidden_size, config.dropout)
            for _ in range(config.num_layers)
        ])
        self.final_norm = nn.LayerNorm(config.d_model)

    def forward(
        self,
        input_ids: Tensor,
        *,
        attention_mask: Tensor | None = None,
        caches: list[KVCache | None] | None = None,
        use_cache: bool = False,
    ) -> tuple[Tensor, list[KVCache | None]]:
        if caches is not None and len(caches) != len(self.layers):
            raise ValueError("one cache entry is required per transformer layer")
        past_length = 0
        if caches and caches[0] is not None:
            past_length = caches[0].length
        hidden = self.positions(self.embeddings(input_ids), offset=past_length)
        next_caches: list[KVCache | None] = []
        for index, layer in enumerate(self.layers):
            layer_cache = None if caches is None else caches[index]
            hidden, updated = layer(
                hidden, attention_mask=attention_mask, cache=layer_cache, use_cache=use_cache
            )
            next_caches.append(updated)
        return self.final_norm(hidden), next_caches
