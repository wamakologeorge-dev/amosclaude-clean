"""ASGI entrypoint for providers that discover ``api/index.py`` (including Vercel)."""

from amoscloud_ai.first_production_app import app

__all__ = ["app"]
