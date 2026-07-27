"""Storage-controller application composition root."""

import os

os.environ.setdefault(
    "AMOSCLAUD_STORAGE_ALLOWED_MOUNTS",
    "/var/lib/amosclaud/repositories,/data/repositories,/mnt/amosclaud-volumes",
)

try:  # Package import for tests and installed tooling.
    from .controller import app  # noqa: E402
    from .volume_api import router as volume_router  # noqa: E402
except ImportError:  # Top-level import inside the controller container.
    from controller import app  # noqa: E402
    from volume_api import router as volume_router  # noqa: E402

app.include_router(volume_router)

__all__ = ["app"]
