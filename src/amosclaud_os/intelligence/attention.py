"""Attention building block for Amosclaud Autonomous intelligence.

This module does not create a second Autonomous brain. It is a reusable neural
component that may be used by model services selected by the canonical
``AutonomousKernel``.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class ScaledDotProductAttention(nn.Module):
    """Project inputs into Q/K/V and compute scaled dot-product attention.

    Args:
        d_model: Input and output embedding width.
        dropout: Dropout applied to attention probabilities.
        bias: Whether Q/K/V projection layers use bias.

    Input shape:
        ``[batch, sequence, d_model]``

    Mask:
        Boolean mask broadcastable to ``[batch, sequence, sequence]`` where
        ``True`` means the position may be attended to.
    """

    def __init__(self, d_model: int, dropout: float = 0.0, bias: bool = True) -> None:
        super().__init__()
        if d_model <= 0:
            raise ValueError("d_model must be greater than zero")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in the range [0, 1)")

        self.d_model = d_model
        self.q_linear = nn.Linear(d_model, d_model, bias=bias)
        self.k_linear = nn.Linear(d_model, d_model, bias=bias)
        self.v_linear = nn.Linear(d_model, d_model, bias=bias)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: Tensor,
        mask: Optional[Tensor] = None,
        *,
        return_weights: bool = False,
    ) -> Tensor | Tuple[Tensor, Tensor]:
        if x.ndim != 3:
            raise ValueError("x must have shape [batch, sequence, d_model]")
        if x.size(-1) != self.d_model:
            raise ValueError(
                f"expected final dimension {self.d_model}, received {x.size(-1)}"
            )

        query = self.q_linear(x)
        key = self.k_linear(x)
        value = self.v_linear(x)

        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(query.size(-1))

        if mask is not None:
            allowed = mask.to(device=scores.device, dtype=torch.bool)
            scores = scores.masked_fill(~allowed, torch.finfo(scores.dtype).min)

        weights = F.softmax(scores, dim=-1)
        weights = self.dropout(weights)
        context = torch.matmul(weights, value)

        if return_weights:
            return context, weights
        return context
