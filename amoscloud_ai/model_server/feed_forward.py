"""Transformer feed-forward networks."""
from __future__ import annotations

from torch import Tensor, nn
import torch.nn.functional as F


class FeedForward(nn.Module):
    def __init__(self, d_model: int, hidden_size: int | None = None, dropout: float = 0.0, gated: bool = True) -> None:
        super().__init__()
        hidden = hidden_size or 4 * d_model
        if d_model <= 0 or hidden <= 0:
            raise ValueError("dimensions must be greater than zero")
        self.gated = gated
        self.input = nn.Linear(d_model, hidden * (2 if gated else 1))
        self.output = nn.Linear(hidden, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor) -> Tensor:
        hidden = self.input(x)
        if self.gated:
            gate, value = hidden.chunk(2, dim=-1)
            hidden = F.silu(gate) * value
        else:
            hidden = F.gelu(hidden)
        return self.output(self.dropout(hidden))
