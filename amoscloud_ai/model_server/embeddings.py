"""Token embedding layer used by local transformer model services."""
from __future__ import annotations

import math
import torch
from torch import Tensor, nn


class TokenEmbeddings(nn.Module):
    def __init__(self, vocab_size: int, d_model: int, padding_idx: int | None = None, scale: bool = True) -> None:
        super().__init__()
        if vocab_size <= 0 or d_model <= 0:
            raise ValueError("vocab_size and d_model must be greater than zero")
        self.embedding = nn.Embedding(vocab_size, d_model, padding_idx=padding_idx)
        self.scale = math.sqrt(d_model) if scale else 1.0

    def forward(self, token_ids: Tensor) -> Tensor:
        if token_ids.dtype not in (torch.int32, torch.int64):
            raise TypeError("token_ids must contain integer indices")
        return self.embedding(token_ids) * self.scale
