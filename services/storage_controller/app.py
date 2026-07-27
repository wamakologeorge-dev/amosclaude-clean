"""Storage-controller application composition root."""

import os

os.environ.setdefault(
    "AMOSCLAUD_STORAGE_ALLOWED_MOUNTS",
    "/var/lib/amosclaud/repositories,/data/repositories,/mnt/amosclaud-volumes",
)

from controller import app  # noqa: E402
from volume_api import router as volume_router  # noqa: E402

app.include_router(volume_router)

__all__ = ["app"]
