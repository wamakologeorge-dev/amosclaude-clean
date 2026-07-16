"""Sinusoidal and learned positional encodings."""
from __future__ import annotations

import math

import torch
from torch import Tensor, nn


class SinusoidalPositionalEncoding(nn.Module):
    def __init__(
        self,
        d_model: int,
        max_length: int = 8192,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if d_model <= 0 or max_length <= 0:
            raise ValueError(
                "d_model and max_length must be greater than zero"
            )
        position = torch.arange(
            max_length,
            dtype=torch.float32,
        ).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float32)
            * (-math.log(10000.0) / d_model)
        )
        table = torch.zeros(max_length, d_model)
        table[:, 0::2] = torch.sin(position * div_term)
        odd_width = table[:, 1::2].shape[1]
        table[:, 1::2] = torch.cos(position * div_term[:odd_width])
        self.register_buffer(
            "table",
            table.unsqueeze(0),
            persistent=False,
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor, offset: int = 0) -> Tensor:
        length = x.size(1)
        if offset < 0 or offset + length > self.table.size(1):
            raise ValueError("position range exceeds configured maximum")
        positions = self.table[:, offset : offset + length]
        return self.dropout(
            x + positions.to(dtype=x.dtype, device=x.device)
        )


class LearnedPositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_length: int = 8192) -> None:
        super().__init__()
        if d_model <= 0 or max_length <= 0:
            raise ValueError(
                "d_model and max_length must be greater than zero"
            )
        self.embedding = nn.Embedding(max_length, d_model)

    def forward(self, x: Tensor, offset: int = 0) -> Tensor:
        positions = torch.arange(
            offset,
            offset + x.size(1),
            device=x.device,
        )
        return x + self.embedding(positions).unsqueeze(0)
