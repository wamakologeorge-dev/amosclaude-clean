"""Uvicorn launcher for the dedicated preview service."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "preview_service.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        workers=int(os.getenv("PREVIEW_WORKERS", "1")),
    )


if __name__ == "__main__":
    main()
