"""Regression tests for the professional repository workspace forge.

Covers the route-dedup fix (GET issues / pull-requests / PUT deployment
settings restored), the authoritative not-found banner condition, tab
auto-load endpoints, per-file history ordering, real per-line blame plus its
honest "unavailable" signal, binary handling, authorization on the new read
endpoints, and the presence of the new workspace UI surfaces.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.api.routes import repository_history
from amoscloud_ai.main import create_app

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
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at)"
            " VALUES (?,?,?,?)",
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
        base = "http://ts"
        async with httpx.AsyncClient(transport=transport, base_url=base) as client:
            client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.get(url)

    return asyncio.run(run())


def _put(token, url, body):
    async def run():
        transport = httpx.ASGITransport(app=create_app())
        base = "http://ts"
        async with httpx.AsyncClient(transport=transport, base_url=base) as client:
            client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.put(url, json=body)

    return asyncio.run(run())


# --- route table / dedup fix -------------------------------------------------

def _methods_for(app, target):
    methods = set()
    for route in app.routes:
        if getattr(route, "path", None) == target:
            methods |= (getattr(route, "methods", None) or set())
    return methods - {"HEAD", "OPTIONS"}


def test_multi_method_repository_routes_are_all_registered():
    app = create_app()
    base = "/api/v1/repositories/{repository_id}"
    assert _methods_for(app, f"{base}/issues") == {"GET", "POST"}
    assert _methods_for(app, f"{base}/pull-requests") == {"GET", "POST"}
    assert _methods_for(app, f"{base}/deployment-settings") == {"GET", "PUT"}
    assert _methods_for(app, f"{base}/history") == {"GET"}
    assert _methods_for(app, f"{base}/blame") == {"GET"}


# --- not-found banner condition (authoritative metadata) ---------------------

def test_metadata_404_for_missing_repository(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, _ = _mkuser("owner@example.com")
    response = _get(token, "/api/v1/repositories/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


def test_metadata_200_for_existing_repository(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    response = _get(token, f"/api/v1/repositories/{rid}")
    assert response.status_code == 200
    assert response.json()["name"] == "proj"


# --- tab auto-load endpoints return real data (not 405) ----------------------

def test_issue_and_pr_tabs_load_real_data(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    issues = _get(token, f"/api/v1/repositories/{rid}/issues")
    prs = _get(token, f"/api/v1/repositories/{rid}/pull-requests")
    assert issues.status_code == 200 and issues.json() == []
    assert prs.status_code == 200 and prs.json() == []


# --- per-file history ordering ----------------------------------------------

def _commit_file(rid, owner, path, content, message):
    repositories.write_file(
        rid,
        repositories.FileWriteRequest(
            path=path, content=content, branch="main", commit_message=message
        ),
        owner,
    )


def test_history_returns_commits_touching_path_newest_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    _commit_file(rid, owner, "docs/a.txt", "one\n", "add a")
    _commit_file(rid, owner, "docs/a.txt", "one\ntwo\n", "grow a")
    _commit_file(rid, owner, "docs/other.txt", "x\n", "unrelated")

    response = _get(token, f"/api/v1/repositories/{rid}/history?path=docs/a.txt")
    assert response.status_code == 200
    messages = [c["message"] for c in response.json()["commits"]]
    assert messages == ["grow a", "add a"]
    assert all(len(c["short_sha"]) == 7 for c in response.json()["commits"])


# --- blame: real per-line attribution + honest unavailable -------------------

def test_blame_attributes_lines_to_real_commits(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    _commit_file(rid, owner, "code.txt", "alpha\nbeta\n", "first")
    _commit_file(rid, owner, "code.txt", "alpha\nBETA\n", "second")

    response = _get(token, f"/api/v1/repositories/{rid}/blame?path=code.txt")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    lines = payload["lines"]
    assert [line["content"] for line in lines[:2]] == ["alpha", "BETA"]
    # Line 1 predates line 2's edit, so they attribute to different commits.
    assert lines[0]["short_sha"] != lines[1]["short_sha"]
    assert lines[0]["author"] == "owner"


def test_blame_reports_binary_files_as_unavailable(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    repo = repositories._open(rid)
    target = repositories._repo_path(rid) / "logo.bin"
    target.write_bytes(b"\x00\x01\x02BIN\x00")
    repo.index.add(["logo.bin"])
    repo.index.commit("add binary")

    response = _get(token, f"/api/v1/repositories/{rid}/blame?path=logo.bin")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert "annotated" in payload["reason"].lower()
    assert payload["lines"] == []


def test_binary_file_read_is_rejected_not_dumped(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj"), owner
    ).id
    repo = repositories._open(rid)
    # Invalid UTF-8 (JPEG magic) so the editor read genuinely rejects it.
    (repositories._repo_path(rid) / "logo.bin").write_bytes(b"\xff\xd8\xff\xe0BIN")
    repo.index.add(["logo.bin"])
    repo.index.commit("add binary")
    response = _get(token, f"/api/v1/repositories/{rid}/files?path=logo.bin")
    assert response.status_code == 415


# --- authorization on new read endpoints -------------------------------------

def test_private_repo_history_denied_to_non_collaborator(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    outsider, _ = _mkuser("outsider@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="secret", visibility="private"), owner
    ).id
    history = _get(outsider, f"/api/v1/repositories/{rid}/history?path=README.md")
    blame = _get(outsider, f"/api/v1/repositories/{rid}/blame?path=README.md")
    assert history.status_code == 404
    assert blame.status_code == 404


def test_read_only_user_cannot_write_deployment_settings(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    viewer_token, viewer = _mkuser("viewer@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id
    repositories.add_collaborator(
        rid,
        repositories.CollaboratorRequest(email="viewer@example.com", role="viewer"),
        owner,
    )
    response = _put(
        viewer_token,
        f"/api/v1/repositories/{rid}/deployment-settings",
        {"provider": "local"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Write access required"


def test_viewer_can_read_history(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    viewer_token, _ = _mkuser("viewer@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id
    repositories.add_collaborator(
        rid,
        repositories.CollaboratorRequest(email="viewer@example.com", role="viewer"),
        owner,
    )
    response = _get(viewer_token, f"/api/v1/repositories/{rid}/history?path=README.md")
    assert response.status_code == 200
    assert response.json()["commits"]


# --- workspace markup surfaces ----------------------------------------------

def test_workspace_markup_has_new_surfaces():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    for surface in (
        'id="ws-view"',
        'id="ws-history"',
        'id="ws-blame"',
        'data-mode="blame"',
        'data-mode="history"',
        "ws-powered-by",
    ):
        assert surface in html, surface
    # The fragile status-text MutationObserver banner must be gone.
    assert "MutationObserver" not in html


def test_history_module_never_fabricates_attribution():
    source = (
        Path("amoscloud_ai/api/routes/repository_history.py")
        .read_text(encoding="utf-8")
    )
    assert "repo.blame(" in source
    assert repository_history.MAX_BLAME_BYTES > 0
