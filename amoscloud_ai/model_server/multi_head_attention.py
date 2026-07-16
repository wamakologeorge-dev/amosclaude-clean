"""Production-oriented multi-head self-attention with causal masking and KV caching."""
from __future__ import annotations

import math
import torch
from torch import Tensor, nn
import torch.nn.functional as F

from .kv_cache import KVCache


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, num_heads: int, dropout: float = 0.0, causal: bool = True) -> None:
        super().__init__()
        if d_model <= 0 or num_heads <= 0 or d_model % num_heads:
            raise ValueError("d_model must be positive and divisible by num_heads")
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.causal = causal
        self.qkv = nn.Linear(d_model, 3 * d_model)
        self.output = nn.Linear(d_model, d_model)
        self.dropout = dropout

    def _split(self, x: Tensor) -> Tensor:
        batch, length, _ = x.shape
        return x.view(batch, length, self.num_heads, self.head_dim).transpose(1, 2)

    def _merge(self, x: Tensor) -> Tensor:
        batch, _, length, _ = x.shape
        return x.transpose(1, 2).contiguous().view(batch, length, self.d_model)

    def forward(
        self,
        x: Tensor,
        *,
        attention_mask: Tensor | None = None,
        cache: KVCache | None = None,
        use_cache: bool = False,
    ) -> tuple[Tensor, KVCache | None]:
        if x.ndim != 3 or x.size(-1) != self.d_model:
            raise ValueError("x must have shape [batch, sequence, d_model]")
        query, key, value = self.qkv(x).chunk(3, dim=-1)
        query, key, value = self._split(query), self._split(key), self._split(value)
        past_length = 0 if cache is None else cache.length
        active_cache = cache or KVCache()
        if use_cache or cache is not None:
            key, value = active_cache.append(key, value)
        else:
            active_cache = None

        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.head_dim)
        query_length, key_length = query.size(-2), key.size(-2)
        if self.causal:
            q_positions = torch.arange(past_length, past_length + query_length, device=x.device).unsqueeze(-1)
            k_positions = torch.arange(key_length, device=x.device).unsqueeze(0)
            causal_mask = k_positions > q_positions
            scores = scores.masked_fill(causal_mask.view(1, 1, query_length, key_length), torch.finfo(scores.dtype).min)
        if attention_mask is not None:
            mask = attention_mask.to(device=x.device, dtype=torch.bool)
            while mask.ndim < scores.ndim:
                mask = mask.unsqueeze(1)
            scores = scores.masked_fill(~mask, torch.finfo(scores.dtype).min)
        weights = F.softmax(scores, dim=-1)
        weights = F.dropout(weights, p=self.dropout, training=self.training)
        context = torch.matmul(weights, value)
        return self.output(self._merge(context)), active_cache
