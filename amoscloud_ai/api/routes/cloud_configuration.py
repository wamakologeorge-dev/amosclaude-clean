"""Read-only status for Amosclaud server-managed cloud configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from amoscloud_ai.api.routes.github_repositories import _current_user
from amoscloud_ai.cloud_configuration import load_cloud_configuration

router = APIRouter(prefix="/platform", tags=["cloud-configuration"])


@router.get("/cloud-configuration")
def cloud_configuration_status(user=Depends(_current_user)) -> dict:
    """Return non-secret gateway and organization policy facts.

    There is intentionally no write endpoint. These files are controlled by the
    Amosclaud server administrator and mounted into every application node.
    """

    del user
    return load_cloud_configuration().public_status()
