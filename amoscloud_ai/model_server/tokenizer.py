"""Tokenizer contracts and a safe byte-level fallback tokenizer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import torch


class TokenizerProtocol(Protocol):
    eos_token_id: int | None

    def encode(self, text: str, return_tensors: str | None = None): ...
    def decode(self, token_ids, skip_special_tokens: bool = True) -> str: ...


@dataclass
class ByteTokenizer:
    """Small deterministic tokenizer for tests and offline plumbing.

    It is not a replacement for a trained BPE tokenizer, but it provides the
    same encode/decode contract so the model server can be exercised without
    downloading external assets.
    """

    eos_token_id: int = 256
    vocab_size: int = 257

    def encode(self, text: str, return_tensors: str | None = None):
        ids = list(text.encode("utf-8"))
        if return_tensors == "pt":
            return torch.tensor([ids], dtype=torch.long)
        return ids

    def decode(self, token_ids: Sequence[int] | torch.Tensor, skip_special_tokens: bool = True) -> str:
        if isinstance(token_ids, torch.Tensor):
            token_ids = token_ids.detach().cpu().flatten().tolist()
        data = bytearray()
        for token_id in token_ids:
            value = int(token_id)
            if skip_special_tokens and value == self.eos_token_id:
                continue
            if 0 <= value <= 255:
                data.append(value)
        return data.decode("utf-8", errors="replace")
