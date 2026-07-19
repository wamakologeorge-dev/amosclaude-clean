"""Pre-normalized transformer decoder block."""
from __future__ import annotations

from torch import Tensor, nn

from .feed_forward import FeedForward
from .kv_cache import KVCache
from .multi_head_attention import MultiHeadAttention


class TransformerBlock(nn.Module):
    def __init__(
        self,
        d_model: int,
        num_heads: int,
        hidden_size: int | None = None,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.attention_norm = nn.LayerNorm(d_model)
        self.attention = MultiHeadAttention(
            d_model,
            num_heads,
            dropout=dropout,
            causal=True,
        )
        self.ffn_norm = nn.LayerNorm(d_model)
        self.feed_forward = FeedForward(
            d_model,
            hidden_size,
            dropout=dropout,
            gated=True,
        )
        self.residual_dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: Tensor,
        *,
        attention_mask: Tensor | None = None,
        cache: KVCache | None = None,
        use_cache: bool = False,
    ) -> tuple[Tensor, KVCache | None]:
        attended, updated_cache = self.attention(
            self.attention_norm(x),
            attention_mask=attention_mask,
            cache=cache,
            use_cache=use_cache,
        )
        x = x + self.residual_dropout(attended)
        x = x + self.residual_dropout(
            self.feed_forward(self.ffn_norm(x))
        )
        return x, updated_cache
