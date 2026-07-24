"""Canonical source package for the unified Amosclaud Autonomous platform.

The :mod:`src` namespace contains implementation modules used by the platform,
Autonomous kernel, Fixer, repository services, and compatibility entry points.
Runtime applications must be composed through ``amoscloud_ai.main.create_app``;
modules under this package must not create an independent Agent brain.
"""

from __future__ import annotations

__version__ = "3.0.0"
__author__ = "Amosclaud"
__email__ = "dev@amosclaud.com"


def create_platform_app():
    """Create the single canonical Amosclaud FastAPI application lazily.

    The lazy import avoids loading the web application when callers only need
    utility modules from ``src`` and prevents a second top-level ``main`` app
    from being constructed during test discovery.
    """

    from amoscloud_ai.main import create_app

    return create_app()


__all__ = ["__version__", "__author__", "__email__", "create_platform_app"]
