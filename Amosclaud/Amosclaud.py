"""Compatibility entry point for the unified Amosclaud Autonomous platform.

Historically this module created a second, partial FastAPI application containing
only the Git hosting router.  That split route registration and allowed imports
of ``Amosclaud.Amosclaud`` to expose a different platform from root ``main``.
It now exports the canonical application factory and application instance.
"""

from amoscloud_ai.main import create_app

app = create_app()

__all__ = ["app", "create_app"]
