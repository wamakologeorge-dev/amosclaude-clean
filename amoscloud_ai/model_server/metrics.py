"""Thread-safe generation metrics for the Amosclaud model server."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter


@dataclass
class GenerationMetrics:
    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens_reused: int = 0
    total_latency_seconds: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(self, *, input_tokens: int, output_tokens: int, latency_seconds: float, cache_tokens_reused: int = 0, failed: bool = False) -> None:
        with self._lock:
            self.requests += 1
            self.failures += int(failed)
            self.input_tokens += max(0, input_tokens)
            self.output_tokens += max(0, output_tokens)
            self.cache_tokens_reused += max(0, cache_tokens_reused)
            self.total_latency_seconds += max(0.0, latency_seconds)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            generated = max(1, self.output_tokens)
            return {
                "requests": self.requests,
                "failures": self.failures,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_tokens_reused": self.cache_tokens_reused,
                "average_latency_seconds": self.total_latency_seconds / max(1, self.requests),
                "tokens_per_second": self.output_tokens / max(self.total_latency_seconds, 1e-9),
                "cache_reuse_ratio": self.cache_tokens_reused / generated,
            }


class Timer:
    def __enter__(self) -> "Timer":
        self.started = perf_counter()
        self.elapsed = 0.0
        return self

    def __exit__(self, *_exc) -> None:
        self.elapsed = perf_counter() - self.started
