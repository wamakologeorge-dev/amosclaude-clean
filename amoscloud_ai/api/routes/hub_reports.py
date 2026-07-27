"""Hub Compiler HTTP surface: read-only project report cards.

One route, deliberately side-effect free: it reads recorded GitHub App webhook
events and returns a rendered report. Nothing here commits files, writes to a
git repository or calls GitHub.

Authorization reuses the native repository helpers from
:mod:`amoscloud_ai.api.routes.repositories` unchanged: the same
``amos_session`` cookie dependency, the same ``_access`` visibility/collaborator
query, and — because recorded activity can describe a private GitHub
repository even when the platform repository is public — the same
``_require_write`` owner/developer check used by the repository mutation
routes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _require_write,
    _safe_repository_id,
)
from amoscloud_ai.db_migrations import ensure_github_repository_schema
from amoscloud_ai.hub import report as hub_report

router = APIRouter(prefix="/hub", tags=["hub"])


class ReportCounts(BaseModel):
    merged_pull_requests: int
    closed_issues: int
    pushes: int
    commits: int
    contributors: int
    events: int


class MergedPullRequestModel(BaseModel):
    number: int
    title: str
    author: str
    merged_at: str


class ClosedIssueModel(BaseModel):
    number: int
    title: str
    author: str
    closed_at: str


class PushActivityModel(BaseModel):
    pushes: int
    commits: int
    branches: list[str] = Field(default_factory=list)


class ContributorModel(BaseModel):
    login: str
    merged_pull_requests: int
    closed_issues: int
    pushes: int
    commits: int
    total: int


class ActivityModel(BaseModel):
    repository: str
    since: str
    until: str
    counts: ReportCounts
    merged_pull_requests: list[MergedPullRequestModel] = Field(default_factory=list)
    closed_issues: list[ClosedIssueModel] = Field(default_factory=list)
    push_activity: PushActivityModel
    contributors: list[ContributorModel] = Field(default_factory=list)
    first_event_at: str | None = None
    last_event_at: str | None = None
    truncated: bool = False


class NarrativeModel(BaseModel):
    text: str
    source: str
    model_drafted: bool
    reason: str | None = None
    model: str | None = None


class ReportCardResponse(BaseModel):
    repository_id: int
    github_full_name: str
    activity: ActivityModel
    narrative: NarrativeModel
    markdown: str
    html: str
    source_sha256: str


def _github_full_name(db: sqlite3.Connection, repository_id: int) -> str:
    """Resolve the GitHub repository this platform repository is linked to.

    The report may only ever read events for the linked repository. A caller
    can never name an arbitrary GitHub repository, which is what keeps one
    user's activity out of another user's report.
    """

    ensure_github_repository_schema(db)
    row = db.execute(
        "SELECT github_full_name FROM repositories WHERE id = ?",
        (repository_id,),
    ).fetchone()
    full_name = str((row["github_full_name"] if row else "") or "").strip()
    if not full_name:
        raise HTTPException(
            status_code=409,
            detail=(
                "This repository is not linked to a GitHub repository, so no "
                "GitHub activity has been recorded for it."
            ),
        )
    return full_name


@router.get(
    "/repositories/{repository_id}/report-card",
    response_model=ReportCardResponse,
    summary="Compile a project report card from recorded GitHub activity",
)
def repository_report_card(
    repository_id: int,
    since: datetime | None = Query(
        default=None,
        description="Inclusive start of the window (UTC). Defaults to 7 days ago.",
    ),
    until: datetime | None = Query(
        default=None,
        description="Inclusive end of the window (UTC). Defaults to now.",
    ),
    narrative: bool = Query(
        default=True,
        description="Attempt a model-drafted narrative. Counts never depend on it.",
    ),
    user: sqlite3.Row = Depends(_current_user),
) -> ReportCardResponse:
    """Return the structured summary, Markdown and sanitized HTML report."""

    safe_repository_id = _safe_repository_id(repository_id)
    with _db() as db:
        row = _access(db, safe_repository_id, user["id"])
        _require_write(row)
        full_name = _github_full_name(db, safe_repository_id)
    try:
        card = hub_report.build_report_card(
            repository=full_name,
            repository_id=safe_repository_id,
            since=since,
            until=until,
            include_narrative=narrative,
        )
    except hub_report.HubReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = card.to_dict()
    return ReportCardResponse(
        repository_id=safe_repository_id,
        github_full_name=full_name,
        activity=ActivityModel(**payload["activity"]),
        narrative=NarrativeModel(**payload["narrative"]),
        markdown=card.markdown,
        html=card.html,
        source_sha256=card.source_sha256,
    )
