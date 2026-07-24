"""Key-value cache primitives for autoregressive attention."""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass
class KVCache:
    key: Tensor | None = None
    value: Tensor | None = None
    sequence_dim: int = 2
    max_length: int | None = None

    @property
    def length(self) -> int:
        if self.key is None:
            return 0
        return int(self.key.size(self.sequence_dim))

    def append(
        self,
        new_key: Tensor,
        new_value: Tensor,
    ) -> tuple[Tensor, Tensor]:
        if new_key.shape != new_value.shape:
            raise ValueError(
                "new key and value tensors must have the same shape"
            )
        if new_key.ndim < 3:
            raise ValueError("KV tensors must have at least three dimensions")

        if self.key is None:
            key, value = new_key, new_value
        else:
            if self.value is None:
                raise ValueError("KV cache key exists without a value tensor")
            same_prefix = (
                self.key.shape[:self.sequence_dim]
                == new_key.shape[:self.sequence_dim]
            )
            same_suffix = (
                self.key.shape[self.sequence_dim + 1:]
                == new_key.shape[self.sequence_dim + 1:]
            )
            if not (same_prefix and same_suffix):
                raise ValueError(
                    "new KV tensors are incompatible with the existing cache"
                )
            key = torch.cat((self.key, new_key), dim=self.sequence_dim)
            value = torch.cat((self.value, new_value), dim=self.sequence_dim)

        if (
            self.max_length is not None
            and key.size(self.sequence_dim) > self.max_length
        ):
            start = key.size(self.sequence_dim) - self.max_length
            key = key.narrow(self.sequence_dim, start, self.max_length)
            value = value.narrow(self.sequence_dim, start, self.max_length)

        self.key, self.value = key, value
        return key, value

    def clear(self) -> None:
        self.key = None
        self.value = None

    def detach(self) -> "KVCache":
        return KVCache(
            None if self.key is None else self.key.detach(),
            None if self.value is None else self.value.detach(),
            self.sequence_dim,
            self.max_length,
        )


def apply_kv_cache(
    new_k: Tensor,
    new_v: Tensor,
    past_kv_cache: tuple[Tensor, Tensor] | None = None,
    sequence_dim: int = 2,
) -> tuple[Tensor, Tensor]:
    cache = KVCache(sequence_dim=sequence_dim)
    if past_kv_cache is not None:
        cache.key, cache.value = past_kv_cache
    return cache.append(new_k, new_v)
