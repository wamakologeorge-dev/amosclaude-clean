"""Live pull-request metadata for imported GitHub repositories.

The native repository surface intentionally keeps Amosclaud-only pull requests in
``solo_development``.  This router is separate: it reads the connected GitHub
repository through the owner's stored OAuth credential so pull requests merged
outside Amosclaud still appear in the workspace.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from amoscloud_ai.api.routes.github_repositories import (
    _connection,
    _current_user,
    _db,
    _decrypt_token,
    _github_headers,
    _owned_github_repository,
)

router = APIRouter(prefix="/github", tags=["github-pull-requests"])


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _nested_text(payload: dict[str, Any], key: str, child: str, limit: int) -> str:
    value = payload.get(key)
    if not isinstance(value, dict):
        return ""
    return _clean_text(value.get(child), limit)


def github_pull_request_dict(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one GitHub list-pull-requests item for the workspace UI."""

    number = item.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise ValueError("GitHub pull request number is invalid")

    raw_state = _clean_text(item.get("state"), 20).lower() or "unknown"
    merged_at = _clean_text(item.get("merged_at"), 80) or None
    state = "merged" if merged_at else raw_state
    html_url = _clean_text(item.get("html_url"), 500)
    if html_url and not html_url.startswith("https://github.com/"):
        html_url = ""

    return {
        "id": number,
        "number": number,
        "source": "github",
        "title": _clean_text(item.get("title"), 500),
        "body": str(item.get("body") or "")[:50_000],
        "state": state,
        "draft": bool(item.get("draft")),
        "head_branch": _nested_text(item, "head", "ref", 300),
        "base_branch": _nested_text(item, "base", "ref", 300),
        "author": _nested_text(item, "user", "login", 100),
        "html_url": html_url,
        "merge_commit": _clean_text(item.get("merge_commit_sha"), 80) or None,
        "created_at": _clean_text(item.get("created_at"), 80) or None,
        "updated_at": _clean_text(item.get("updated_at"), 80) or None,
        "closed_at": _clean_text(item.get("closed_at"), 80) or None,
        "merged_at": merged_at,
    }


@router.get("/repositories/{repository_id}/pull-requests")
async def list_github_pull_requests(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Return recently updated GitHub pull requests, including merged ones."""

    with _db() as db:
        repository = _owned_github_repository(db, repository_id, int(user["id"]))
        connection = _connection(db, int(user["id"]))
        token = _decrypt_token(connection["access_token_ciphertext"])

    pull_requests: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(1, 4):
            response = await client.get(
                f"https://api.github.com/repos/{repository['github_full_name']}/pulls",
                headers=_github_headers(token),
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if response.status_code in {401, 403}:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "The connected GitHub account cannot read pull requests for "
                        "this repository. Reconnect GitHub or check repository access."
                    ),
                )
            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail="The connected GitHub repository could not be found.",
                )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail="GitHub pull requests are temporarily unavailable.",
                )
            try:
                page_items = response.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=502,
                    detail="GitHub returned invalid pull-request data.",
                ) from exc
            if not isinstance(page_items, list):
                raise HTTPException(
                    status_code=502,
                    detail="GitHub returned invalid pull-request data.",
                )
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                try:
                    pull_requests.append(github_pull_request_dict(item))
                except ValueError:
                    continue
            if len(page_items) < 100:
                break

    return {
        "repository_id": repository_id,
        "github_full_name": repository["github_full_name"],
        "source": "github",
        "pull_requests": pull_requests,
        "count": len(pull_requests),
    }
