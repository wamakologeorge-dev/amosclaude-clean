from __future__ import annotations

import threading
from collections import defaultdict


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Registry:
    """Thread-safe, bounded Prometheus registry without an external client dependency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._help: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _labels(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(key), str(value)) for key, value in (labels or {}).items()))

    def counter(self, name: str, amount: float = 1, *, help_text: str = "", labels=None) -> None:
        with self._lock:
            self._help[name] = (help_text or name, "counter")
            self._counters[(name, self._labels(labels))] += amount

    def gauge(self, name: str, value: float, *, help_text: str = "", labels=None) -> None:
        with self._lock:
            self._help[name] = (help_text or name, "gauge")
            self._gauges[(name, self._labels(labels))] = float(value)

    def gauge_add(self, name: str, amount: float, *, help_text: str = "", labels=None) -> None:
        with self._lock:
            self._help[name] = (help_text or name, "gauge")
            key = (name, self._labels(labels))
            self._gauges[key] = self._gauges.get(key, 0) + amount

    def render(self, extra: dict[str, float] | None = None) -> str:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            metadata = dict(self._help)
        for name, value in (extra or {}).items():
            gauges[(name, ())] = float(value)
            metadata.setdefault(name, (name, "gauge"))
        lines: list[str] = []
        for name in sorted(metadata):
            description, kind = metadata[name]
            lines.extend((f"# HELP {name} {_escape(description)}", f"# TYPE {name} {kind}"))
            values = counters if kind == "counter" else gauges
            for (metric, labels), value in sorted(values.items()):
                if metric != name:
                    continue
                suffix = ""
                if labels:
                    suffix = "{" + ",".join(f'{key}="{_escape(val)}"' for key, val in labels) + "}"
                lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + "\n"


registry = Registry()
