"""Scaled dot-product attention for Amosclaud model services."""

from __future__ import annotations

import math

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class ScaledDotProductAttention(nn.Module):
    """Project tokens to Q, K and V and return context-aware representations."""

    def __init__(self, d_model: int, dropout: float = 0.0) -> None:
        super().__init__()
        if d_model <= 0:
            raise ValueError("d_model must be greater than zero")
        self.d_model = d_model
        self.q_linear = nn.Linear(d_model, d_model)
        self.k_linear = nn.Linear(d_model, d_model)
        self.v_linear = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor, mask: Tensor | None = None) -> tuple[Tensor, Tensor]:
        if x.ndim != 3 or x.size(-1) != self.d_model:
            raise ValueError("x must have shape [batch, sequence, d_model]")
        query = self.q_linear(x)
        key = self.k_linear(x)
        value = self.v_linear(x)
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(query.size(-1))
        if mask is not None:
            scores = scores.masked_fill(~mask.to(dtype=torch.bool), float("-inf"))
        weights = self.dropout(F.softmax(scores, dim=-1))
        return torch.matmul(weights, value), weights
