#!/usr/bin/env python3
"""Initialize and run the Amosclaud local-first control plane."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from amoscloud_ai.local_cloud.authority import LocalAuthority


def main() -> None:
    state_dir = Path(
        os.getenv("AMOSCLAUD_LOCAL_STATE_DIR", "~/.amosclaud/local-cloud")
    ).expanduser().resolve()
    authority = LocalAuthority(state_dir)
    state, token = authority.initialize()
    print(f"Amosclaud local instance: {state.instance_id}")
    print(f"State directory: {state_dir}")
    if token:
        print("\nONE-TIME LOCAL AUTHORITY TOKEN")
        print(token)
        print("Store it securely. The plaintext token is not written to disk.\n")
    else:
        print("Local authority already initialized. Use the existing token or rotate it.")
    host = os.getenv("AMOSCLAUD_LOCAL_HOST", "127.0.0.1")
    port = int(os.getenv("AMOSCLAUD_LOCAL_PORT", "8765"))
    uvicorn.run(
        "amoscloud_ai.local_cloud.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
