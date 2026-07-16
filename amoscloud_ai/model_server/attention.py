"""Scaled dot-product attention primitives."""
from __future__ import annotations

import math
import torch
from torch import Tensor, nn
import torch.nn.functional as F


class ScaledDotProductAttention(nn.Module):
    def __init__(self, d_model: int, dropout: float = 0.0) -> None:
        super().__init__()
        if d_model <= 0:
            raise ValueError("d_model must be greater than zero")
        self.q_linear = nn.Linear(d_model, d_model)
        self.k_linear = nn.Linear(d_model, d_model)
        self.v_linear = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor, mask: Tensor | None = None) -> Tensor:
        if x.ndim != 3:
            raise ValueError("x must have shape [batch, sequence, d_model]")
        query = self.q_linear(x)
        key = self.k_linear(x)
        value = self.v_linear(x)
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(query.size(-1))
        if mask is not None:
            boolean_mask = mask.to(device=x.device, dtype=torch.bool)
            while boolean_mask.ndim < scores.ndim:
                boolean_mask = boolean_mask.unsqueeze(1)
            scores = scores.masked_fill(~boolean_mask, torch.finfo(scores.dtype).min)
        weights = self.dropout(F.softmax(scores, dim=-1))
        return torch.matmul(weights, value)


def scaled_dot_product_attention(query: Tensor, key: Tensor, value: Tensor, mask: Tensor | None = None) -> tuple[Tensor, Tensor]:
    if query.size(-1) != key.size(-1):
        raise ValueError("query and key dimensions must match")
    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(query.size(-1))
    if mask is not None:
        scores = scores.masked_fill(~mask.to(dtype=torch.bool, device=scores.device), torch.finfo(scores.dtype).min)
    weights = F.softmax(scores, dim=-1)
    return torch.matmul(weights, value), weights
