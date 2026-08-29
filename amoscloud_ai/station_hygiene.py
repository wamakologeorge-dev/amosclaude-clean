"""Keep worker stations looking like the clean CI machine repositories expect.

The process-sandbox worker shares its filesystem with the platform service.
Whatever deployment method built the station (container image, buildpack, or
bare checkout), the service's own source tree usually lives at ``/app`` and
carries workspace markers such as ``docker-compose.selfhost.yml``. Repository
test suites legitimately probe "an unrelated folder must NOT resolve to a
workspace" by walking a temp directory's parents to ``/`` — and on a station
that leaks its own installation, that walk finds a phantom workspace no clean
CI machine has, inverting the repository's rejection tests.

Build-time image hygiene cannot be trusted here: the deployment path is not
guaranteed to use any particular Dockerfile. The worker therefore scrubs the
markers itself immediately before running an Action, which is correct on
every deployment method and self-heals after every redeploy.

Self-hosted stations that intentionally run Actions from a live source
checkout and still manage that checkout with the ``amos`` CLI can keep their
markers with ``AMOSCLAUD_KEEP_STATION_MARKERS=1``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

KEEP_ENV = "AMOSCLAUD_KEEP_STATION_MARKERS"

# Every path outside the disposable checkout that workspace discovery would
# match while walking a sandbox temp directory's parents (…/tmp, /) on a
# station whose own installation lives at /app.
STATION_MARKERS: tuple[str, ...] = (
    "/app/docker-compose.selfhost.yml",
    "/docker-compose.selfhost.yml",
    "/Infrastructure/docker-compose.yml",
    "/tmp/docker-compose.selfhost.yml",
    "/tmp/app/docker-compose.selfhost.yml",
    "/tmp/Infrastructure/docker-compose.yml",
)


def scrub_station_markers(
    markers: Iterable[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Delete the station's own workspace markers; never raises.

    Returns ``(removed, stubborn)``: marker paths that were deleted and marker
    paths that exist but could not be deleted. Honors ``KEEP_ENV`` as an
    explicit self-host opt-out.
    """
    if markers is None:
        markers = STATION_MARKERS
    if os.getenv(KEEP_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return [], []
    removed: list[str] = []
    stubborn: list[str] = []
    for raw in markers:
        path = Path(raw)
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError:
            stubborn.append(str(path))
    return removed, stubborn


def station_hygiene_log_lines() -> list[str]:
    """Scrub and describe the result as run-log-ready sentences."""
    removed, stubborn = scrub_station_markers()
    lines = [
        "Station hygiene: removed the worker station's own workspace marker "
        f"{path} so repository tests see the clean machine a fresh CI provides."
        for path in removed
    ]
    lines.extend(
        "Station hygiene: could not remove the workspace marker "
        f"{path}; repository workspace-discovery tests may see a phantom workspace."
        for path in stubborn
    )
    return lines
