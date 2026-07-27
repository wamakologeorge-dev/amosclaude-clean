"""Storage-controller application composition root."""

from controller import app
from volume_api import router as volume_router

app.include_router(volume_router)

__all__ = ["app"]
