"""Entry point: ``python -m station``."""

from __future__ import annotations

import sys

from station.agent import StationAgent
from station.config import ConfigError, StationConfig
from station.logs import configure_logging


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"-h", "--help"}:
        print(__doc__ or "")
        print("Configure the agent with environment variables; see station/README.md.")
        return 0
    try:
        config = StationConfig.from_env()
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    logger = configure_logging(config.log_level, secrets=[config.station_token])
    agent = StationAgent(config, logger=logger)
    try:
        agent.run()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        agent.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
