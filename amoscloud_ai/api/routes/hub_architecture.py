"""Hub Compiler HTTP surface: read-only repository architecture maps.

One route, deliberately side-effect free. It statically analyses the files
already stored for a native repository and returns Mermaid diagrams, Markdown
and sanitized HTML. Nothing here imports or executes repository code, commits a
file, changes a branch or calls GitHub.

Authorization
-------------
The route reuses the native repository helpers from
:mod:`amoscloud_ai.api.routes.repositories` unchanged: the same ``amos_session``
cookie dependency and the same ``_access`` visibility/collaborator query.

Unlike :mod:`amoscloud_ai.api.routes.hub_reports` it does **not** additionally
require write access, and that difference is deliberate. The report card can
describe activity in a *private GitHub* repository even when the platform
repository is public, which is data the reader may never have been shown. An
architecture map contains nothing but names derived from files that ``_access``
already lets the same caller read verbatim through
``GET /repositories/{id}/tree`` and ``GET /repositories/{id}/files``. Requiring
write access here would be stricter than the routes serving the underlying
bytes, without protecting anything.

The scanned directory is resolved only from the platform's own repository
record via ``repositories._repo_path``; no caller-supplied path ever reaches the
filesystem.

The per-file module list produced by the scan is deliberately **not** returned.
It grows with the repository — this repository alone yields several hundred
entries — and a map is meant to summarise. Counts, top-level units, routers and
routes are returned in full; the per-file detail stays available in-process
through :func:`amoscloud_ai.hub.architecture.scan_architecture`.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from git.exc import GitError
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _open,
    _repo_lock,
    _repo_path,
    _safe_repository_id,
)
from amoscloud_ai.hub import architecture as hub_architecture

router = APIRouter(prefix="/hub", tags=["hub"])


class ArchitectureCounts(BaseModel):
    units: int
    modules: int
    routers: int
    routes: int
    tables: int
    import_edges: int
    files_scanned: int
    skipped: int


class PackageUnitModel(BaseModel):
    name: str
    kind: str
    modules: int
    routers: int
    routes: int


class RouterModel(BaseModel):
    module: str
    path: str
    variable: str
    prefix: str
    tags: list[str] = Field(default_factory=list)
    mounts: list[str] = Field(default_factory=list)


class RouteModel(BaseModel):
    method: str
    path: str
    handler: str
    module: str
    router: str
    mounted: bool


class TableModel(BaseModel):
    name: str
    path: str


class SkippedFileModel(BaseModel):
    path: str
    reason: str


class ArchitectureModel(BaseModel):
    label: str
    counts: ArchitectureCounts
    units: list[PackageUnitModel] = Field(default_factory=list)
    routers: list[RouterModel] = Field(default_factory=list)
    routes: list[RouteModel] = Field(default_factory=list)
    tables: list[TableModel] = Field(default_factory=list)
    import_edges: list[list[str]] = Field(default_factory=list)
    skipped: list[SkippedFileModel] = Field(default_factory=list)
    bytes_read: int
    truncated: bool
    notes: list[str] = Field(default_factory=list)


class ArchitectureMapResponse(BaseModel):
    repository_id: int
    branch: str | None = None
    commit: str | None = None
    architecture: ArchitectureModel
    package_diagram: str
    route_diagram: str
    markdown: str
    html: str
    source_sha256: str


def _worktree_provenance(repository_id: int) -> tuple[str | None, str | None]:
    """Report which branch and commit the scanned working tree is sitting on.

    The scan reads the working tree as it currently stands and never changes it.
    Switching branches would mean ``git reset --hard`` and ``git clean -fd``,
    which is not acceptable in a GET, so the caller is told exactly what was
    scanned instead of being offered a branch to select. A repository with no
    commits yet simply reports ``None``.
    """

    try:
        repository = _open(repository_id)
        try:
            branch = repository.active_branch.name
        except (TypeError, ValueError, GitError):
            branch = None
        try:
            commit = repository.head.commit.hexsha
        except (ValueError, GitError):
            commit = None
        return branch, commit
    except HTTPException:
        raise
    except (GitError, OSError, ValueError):  # pragma: no cover - defensive
        return None, None


@router.get(
    "/repositories/{repository_id}/architecture",
    response_model=ArchitectureMapResponse,
    summary="Map a repository's Python structure and route surface as Mermaid",
)
def repository_architecture(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> ArchitectureMapResponse:
    """Return the structural map, both Mermaid diagrams, Markdown and HTML."""

    safe_repository_id = _safe_repository_id(repository_id)
    with _db() as db:
        row = _access(db, safe_repository_id, user["id"])
        label = str(row["name"] or "repository")
    with _repo_lock(safe_repository_id):
        root = _repo_path(safe_repository_id)
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="Repository storage not found")
        branch, commit = _worktree_provenance(safe_repository_id)
        try:
            document = hub_architecture.build_architecture_document(
                root=root,
                repository_id=safe_repository_id,
                label=label,
            )
        except hub_architecture.ArchitectureScanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = document.to_dict()
    return ArchitectureMapResponse(
        repository_id=safe_repository_id,
        branch=branch,
        commit=commit,
        architecture=ArchitectureModel(
            **{
                key: value
                for key, value in payload["architecture"].items()
                if key != "modules"
            }
        ),
        package_diagram=document.package_diagram,
        route_diagram=document.route_diagram,
        markdown=document.markdown,
        html=document.html,
        source_sha256=document.source_sha256,
    )
