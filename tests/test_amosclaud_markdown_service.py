"""Regression tests for the Amosclaud repository Markdown service."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.main import create_app
from amoscloud_ai.markdown_service import render_markdown_document


WEB = Path(__file__).resolve().parent.parent / "web"


def _mkuser(email: str):
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)"
            " VALUES (?,?,?,'password',0,?)",
            (email.split("@", 1)[0], email, auth._hash_password("pw"), now.isoformat()),
        )
        uid = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                uid,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return token, user


def _isolate(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")


def _get(token, url):
    async def run():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.get(url)

    return asyncio.run(run())


def test_renderer_supports_repository_markdown_features_and_navigation():
    document = render_markdown_document(
        """# Amosclaud Markdown

- [x] Safe rendering
- [ ] Repository navigation

| Service | State |
| --- | --- |
| Markdown | Ready |

See [the guide](docs/guide.md) and ![logo](assets/logo.png).
""",
        repository_id=42,
        branch="feature/docs",
        source_path="README.md",
    )

    assert '<h1 id="amosclaud-markdown">' in document.html
    assert 'class="task-list-item"' in document.html
    assert "<table>" in document.html
    assert 'data-repository-path="docs/guide.md"' in document.html
    assert "/workspace/42?path=docs%2Fguide.md&amp;branch=feature%2Fdocs" in document.html
    assert "/api/v1/repositories/42/raw?path=assets%2Flogo.png" in document.html
    assert document.outline == (
        {"level": 1, "title": "Amosclaud Markdown", "id": "amosclaud-markdown"},
    )
    assert len(document.source_sha256) == 64


def test_renderer_blocks_raw_html_javascript_and_repository_traversal():
    document = render_markdown_document(
        """<script>alert(1)</script>

[bad](javascript:alert(1))

[escape](../../private.txt)

![unsafe](data:text/html;base64,AAAA)
""",
        repository_id=7,
        branch="main",
        source_path="docs/README.md",
    )

    lowered = document.html.lower()
    assert "<script" not in lowered
    assert "javascript:" not in lowered
    assert "data:text" not in lowered
    assert "private.txt" not in lowered


def test_markdown_endpoint_renders_real_repository_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="markdown-project", description="Rendered docs"),
        owner,
    ).id
    repositories.write_file(
        rid,
        repositories.FileWriteRequest(
            path="README.md",
            branch="main",
            commit_message="Improve README",
            content="# Real README\n\n> Rendered by Amosclaud.\n",
        ),
        owner,
    )

    response = _get(token, f"/api/v1/repositories/{rid}/markdown?path=README.md")
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "README.md"
    assert payload["branch"] == "main"
    assert '<h1 id="real-readme">' in payload["html"]
    assert "Rendered by Amosclaud" in payload["html"]
    assert payload["outline"][0]["title"] == "Real README"


def test_raw_endpoint_serves_only_safe_inline_media(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="media-project"), owner
    ).id
    repo = repositories._open(rid)
    root = repositories._repo_path(rid)
    (root / "assets").mkdir()
    (root / "assets" / "pixel.png").write_bytes(b"\x89PNG\r\n\x1a\nDATA")
    (root / "assets" / "unsafe.svg").write_text("<svg><script>alert(1)</script></svg>")
    repo.index.add(["assets/pixel.png", "assets/unsafe.svg"])
    repo.index.commit("Add README media")

    image = _get(token, f"/api/v1/repositories/{rid}/raw?path=assets/pixel.png")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.headers["x-content-type-options"] == "nosniff"
    assert image.content.startswith(b"\x89PNG")

    svg = _get(token, f"/api/v1/repositories/{rid}/raw?path=assets/unsafe.svg")
    assert svg.status_code == 415


def test_overview_reports_real_repository_counts_and_policy_files(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="overview-project"), owner
    ).id
    repositories.write_file(
        rid,
        repositories.FileWriteRequest(
            path="CONTRIBUTING.md",
            content="# Contributing\n",
            branch="main",
            commit_message="Add contributing guide",
        ),
        owner,
    )
    repositories.write_file(
        rid,
        repositories.FileWriteRequest(
            path="src/app.py",
            content="print('ready')\n",
            branch="main",
            commit_message="Add Python source",
        ),
        owner,
    )

    response = _get(token, f"/api/v1/repositories/{rid}/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["file_count"] >= 4
    assert payload["commit_count"] == 3
    assert payload["branch_count"] == 1
    assert payload["features"]["contributing"] == "CONTRIBUTING.md"
    assert payload["languages"][0]["name"] == "Python"


def test_workspace_loads_backend_markdown_service_and_repository_overview():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    javascript = (WEB / "markdown-service.js").read_text(encoding="utf-8")
    stylesheet = (WEB / "markdown-service.css").read_text(encoding="utf-8")

    assert '/static/markdown-service.css' in html
    assert '/static/markdown-service.js' in html
    assert '/markdown?path=' in javascript
    assert '/overview?branch=' in javascript
    assert 'amos-repository-overview' in javascript
    assert 'data-repository-path' in javascript
    assert '.amos-markdown-body' in stylesheet
    assert '.amos-repository-sidebar' in stylesheet
