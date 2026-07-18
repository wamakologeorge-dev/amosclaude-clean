"""Create and verify real GitHub-backed Amosclaud repositories."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from git.remote import PushInfo
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.github_repositories import (
    _authenticated_clone_url,
    _connection,
    _db as _github_db,
    _decrypt_token,
    _public_remote_url,
)
from amoscloud_ai.api.routes.repositories import (
    RepositoryCreate,
    _current_user,
    _db,
    _open,
    _repo_path,
    create_repository,
)
from amoscloud_ai.api.routes.repository_templates import (
    RepositoryTemplateRequest,
    initialize_repository_template,
)

router = APIRouter(prefix="/repositories", tags=["real-repositories"])


class RealRepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    visibility: Literal["private", "public"] = "private"
    initialize_readme: bool = True
    initialize_gitignore: bool = True
    license: str = "none"


CI_WORKFLOW = """name: Amosclaud CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Detect project
        id: detect
        shell: bash
        run: |
          if [ -f pyproject.toml ] || [ -f requirements.txt ]; then echo "python=true" >> "$GITHUB_OUTPUT"; fi
          if [ -f package.json ]; then echo "node=true" >> "$GITHUB_OUTPUT"; fi
      - name: Set up Python
        if: steps.detect.outputs.python == 'true'
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Verify Python project
        if: steps.detect.outputs.python == 'true'
        shell: bash
        run: |
          python -m pip install --upgrade pip
          python -m pip install pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          if [ -f pyproject.toml ]; then pip install -e .; fi
          python -m compileall .
          if find . -maxdepth 3 -type f -name 'test_*.py' | grep -q .; then python -m pytest -q; fi
      - name: Set up Node
        if: steps.detect.outputs.node == 'true'
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Verify Node project
        if: steps.detect.outputs.node == 'true'
        shell: bash
        run: |
          if [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]; then npm ci; else npm install; fi
          npm test --if-present
          npm run build --if-present
      - name: Verify repository contents
        if: steps.detect.outputs.python != 'true' && steps.detect.outputs.node != 'true'
        run: |
          test -n "$(find . -path ./.git -prune -o -type f -print -quit)"
          echo "Repository contains committed project files."
"""


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _token_for(user_id: int) -> tuple[str, str]:
    with _github_db() as db:
        connection = _connection(db, user_id)
        return _decrypt_token(connection["access_token_ciphertext"]), connection["github_login"]


def _remove_local_repository(repository_id: int) -> None:
    shutil.rmtree(_repo_path(repository_id), ignore_errors=True)
    with _db() as db:
        db.execute("DELETE FROM repositories WHERE id=?", (repository_id,))
        db.commit()


def _push_or_raise(remote, branch: str) -> None:
    results = remote.push(refspec=f"{branch}:{branch}", set_upstream=True)
    if not results or any(result.flags & PushInfo.ERROR for result in results):
        summary = "; ".join(result.summary for result in results) or "No push result was returned"
        raise HTTPException(status_code=502, detail=f"GitHub repository was created but the initial push failed: {summary}")


@router.post("/create-real", status_code=201)
def create_real_repository(body: RealRepositoryCreate, user=Depends(_current_user)) -> dict:
    """Create a local working copy, a real GitHub repository, and push CI-enabled initial history."""
    token, github_login = _token_for(user["id"])
    local = create_repository(
        RepositoryCreate(
            name=body.name,
            description=body.description,
            visibility=body.visibility,
            initialize_readme=body.initialize_readme,
        ),
        user,
    )
    repository_id = local.id
    full_name = f"{github_login}/{local.name}"
    remote_created = False
    try:
        initialize_repository_template(
            repository_id,
            RepositoryTemplateRequest(
                license=body.license,
                initialize_gitignore=body.initialize_gitignore,
                branch=local.default_branch,
            ),
            user,
        )
        repo = _open(repository_id)
        workflow = _repo_path(repository_id) / ".github" / "workflows" / "amosclaud-ci.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(CI_WORKFLOW, encoding="utf-8")
        repo.git.add(A=True)
        if repo.is_dirty(untracked_files=True):
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.commit("Add Amosclaud continuous integration")

        with httpx.Client(timeout=30) as client:
            response = client.post(
                "https://api.github.com/user/repos",
                headers=_headers(token),
                json={
                    "name": local.name,
                    "description": body.description.strip(),
                    "private": body.visibility == "private",
                    "auto_init": False,
                },
            )
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=401, detail="GitHub authorization cannot create repositories; reconnect GitHub with repository access")
        if response.status_code == 422:
            detail = response.json().get("message", "GitHub repository creation was rejected")
            raise HTTPException(status_code=409, detail=detail)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="GitHub repository creation failed")
        metadata = response.json()
        remote_created = True
        full_name = str(metadata.get("full_name") or full_name)

        if "origin" in [remote.name for remote in repo.remotes]:
            remote = repo.remote("origin")
            remote.set_url(_authenticated_clone_url(full_name, token))
        else:
            remote = repo.create_remote("origin", _authenticated_clone_url(full_name, token))
        _push_or_raise(remote, local.default_branch)
        remote.set_url(_public_remote_url(full_name))

        now = datetime.now(timezone.utc).isoformat()
        with _github_db() as db:
            db.execute(
                """UPDATE repositories
                   SET github_full_name=?, github_html_url=?, github_default_branch=?,
                       github_last_sync_at=?, updated_at=? WHERE id=? AND owner_id=?""",
                (
                    full_name,
                    str(metadata.get("html_url") or f"https://github.com/{full_name}"),
                    str(metadata.get("default_branch") or local.default_branch),
                    now,
                    now,
                    repository_id,
                    user["id"],
                ),
            )
            db.commit()
        return {
            **local.model_dump(),
            "github_full_name": full_name,
            "github_html_url": metadata.get("html_url"),
            "commit": repo.head.commit.hexsha,
            "ci_workflow": ".github/workflows/amosclaud-ci.yml",
            "workspace_url": f"/workspace/{repository_id}",
            "remote_created": True,
        }
    except Exception:
        if remote_created:
            try:
                with httpx.Client(timeout=20) as client:
                    client.delete(f"https://api.github.com/repos/{full_name}", headers=_headers(token))
            except Exception:
                pass
        _remove_local_repository(repository_id)
        raise


@router.get("/{repository_id}/real-status")
def real_repository_status(repository_id: int, user=Depends(_current_user)) -> dict:
    """Return persisted remote identity and the latest real GitHub Actions result."""
    token, _ = _token_for(user["id"])
    with _github_db() as db:
        row = db.execute(
            "SELECT * FROM repositories WHERE id=? AND owner_id=?",
            (repository_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    full_name = row["github_full_name"]
    if not full_name:
        return {"repository_id": repository_id, "remote_created": False, "ci": None}
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"https://api.github.com/repos/{full_name}/actions/runs",
            headers=_headers(token),
            params={"per_page": 1},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to read GitHub Actions results")
    runs = response.json().get("workflow_runs") or []
    run = runs[0] if runs else None
    return {
        "repository_id": repository_id,
        "remote_created": True,
        "github_full_name": full_name,
        "github_html_url": row["github_html_url"],
        "last_sync_at": row["github_last_sync_at"],
        "ci": None if not run else {
            "id": run.get("id"),
            "name": run.get("name"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "html_url": run.get("html_url"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
        },
    }
