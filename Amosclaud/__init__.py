"""Public Amosclaud developer-tool namespace.

The package contains low-level byte, bundle, transport, and integrity tools.  It
must not create a second Autonomous Agent or FastAPI application during import.
Use :func:`create_platform_app` when an application object is explicitly needed.
"""

from .byte.core import ByteFrame, ByteFrameError
from .byte.router import ByteRouter
from .byte.system import ByteSystem


def create_platform_app():
    """Return the canonical Amosclaud Autonomous FastAPI application."""

    from amoscloud_ai.main import create_app

    return create_app()


def create_platform_byte_bus(secret: bytes):
    """Create the authenticated internal platform byte bus on demand."""

    from .platform_bus import PlatformByteBus

    return PlatformByteBus(secret)


__all__ = [
    "ByteFrame",
    "ByteFrameError",
    "ByteRouter",
    "ByteSystem",
    "create_platform_app",
    "create_platform_byte_bus",
]
__version__ = "1.1.0"
