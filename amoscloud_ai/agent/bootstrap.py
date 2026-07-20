from __future__ import annotations

import argparse
import os
from pathlib import Path

from .autonomous_keys import AutonomousKeyStore


def configure_direct_connection(*, force: bool = False) -> str:
    """Create an Amosclaud autonomous key and write a private runtime env file."""
    env_path = Path(os.getenv("AMOSCLAUD_AUTONOMOUS_ENV", ".amosclaud/autonomous.env"))
    if env_path.exists() and not force:
        raise RuntimeError(f"Autonomous configuration already exists: {env_path}")

    generated = AutonomousKeyStore().generate()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        "\n".join(
            [
                f"AMOSCLAUD_AUTONOMOUS_API_KEY={generated.secret}",
                f"AMOSCLAUD_API_KEY={generated.secret}",
                "AMOSCLAUD_API_URL=http://127.0.0.1:8000",
                "AMOSCLAUD_CODEX_CONFIG=config/autonomous-codex.toml",
                "AMOSCLAUD_WORKSPACE=workspace/projects",
                "AMOSCLAUD_CODEX_MODEL=amosclaud-folder-v1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return str(env_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Amosclaud autonomous engineering")
    parser.add_argument("--force", action="store_true", help="replace an existing local configuration")
    args = parser.parse_args()
    path = configure_direct_connection(force=args.force)
    print(f"Autonomous connection configured at {path}")
    print("The Amosclaud key was generated locally and connected to the Amosclaud model gateway.")
    print("No external provider API key is required by this configuration.")


if __name__ == "__main__":
    main()
