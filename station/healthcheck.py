"""Container health check: exit 0 only while the backend serves the model.

    python -m station.healthcheck
"""

from __future__ import annotations

import os
import sys

from station.backend import OllamaBackend
from station.config import DEFAULT_BACKEND, DEFAULT_MODEL


def main(env: dict | None = None) -> int:
    env = os.environ if env is None else env
    backend = (env.get("AMOSCLAUD_STATION_BACKEND") or DEFAULT_BACKEND).rstrip("/")
    model = env.get("AMOSCLAUD_STATION_MODEL") or DEFAULT_MODEL
    try:
        timeout = float(env.get("AMOSCLAUD_STATION_PROBE_TIMEOUT") or 10.0)
    except ValueError:
        timeout = 10.0
    probe = OllamaBackend(backend, model, probe_timeout=timeout).probe()
    print(probe.detail)
    return 0 if probe.ready else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
