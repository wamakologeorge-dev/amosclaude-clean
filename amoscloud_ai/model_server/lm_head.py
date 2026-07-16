"""Language-model projection head."""
from __future__ import annotations

from torch import Tensor, nn


class LanguageModelHead(nn.Module):
    def __init__(self, d_model: int, vocab_size: int, bias: bool = False) -> None:
        super().__init__()
        if d_model <= 0 or vocab_size <= 0:
            raise ValueError("d_model and vocab_size must be greater than zero")
        self.projection = nn.Linear(d_model, vocab_size, bias=bias)

    def forward(self, hidden_states: Tensor) -> Tensor:
        return self.projection(hidden_states)

    def tie_weights(self, embedding: nn.Embedding) -> None:
        if embedding.weight.shape != self.projection.weight.shape:
            raise ValueError("embedding and LM-head weights have incompatible shapes")
        self.projection.weight = embedding.weight
