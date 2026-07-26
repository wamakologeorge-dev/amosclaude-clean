"""Contracts for The Editor of the Web repository mirror experience."""

from datetime import datetime, timezone
from pathlib import Path

from amoscloud_ai.api.routes import auth, repositories


WEB = Path(__file__).resolve().parents[1] / "web"


def _user(database: Path):
    repositories.DB_PATH = database
    auth.DB_PATH = database
    now = datetime.now(timezone.utc).isoformat()
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) "
            "VALUES ('Editor Owner','editor@example.com','x','password',0,?)",
            (now,),
        )
        db.commit()
        return db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()


def test_editor_page_exposes_full_file_and_folder_mirror_controls():
    html = (WEB / "editor-of-the-web.html").read_text(encoding="utf-8")

    for surface in (
        "The Editor of the Web",
        'id="eow-tree"',
        'id="eow-editor"',
        'id="eow-new-file"',
        'id="eow-new-folder"',
        'id="eow-rename"',
        'id="eow-delete"',
        'id="eow-pull"',
        'id="eow-push"',
        'id="eow-auto-sync"',
    ):
        assert surface in html

    assert "cdn." not in html.lower()
    assert "/static/highlight.js" in html


def test_editor_client_uses_real_repository_and_github_mirror_routes():
    source = (WEB / "editor-of-the-web.js").read_text(encoding="utf-8")

    for contract in (
        "/api/v1/repositories/${repositoryId}/tree",
        "/api/v1/repositories/${repositoryId}/files",
        "/api/v1/repositories/${repositoryId}/move",
        "/api/v1/repositories/${repositoryId}/branches",
        "/api/v1/github/repositories/${repositoryId}/pull",
        "/api/v1/github/repositories/${repositoryId}/push",
        "imported_repository_id",
    ):
        assert contract in source

    assert "['owner', 'developer']" in source
    assert "beforeunload" in source
    assert "event.ctrlKey || event.metaKey" in source
    assert ".gitkeep" in source


def test_editor_layout_is_mobile_responsive_and_has_focus_mode():
    css = (WEB / "editor-of-the-web.css").read_text(encoding="utf-8")

    assert "@media(max-width:760px)" in css
    assert ".eow-focus-mode" in css
    assert "grid-template-columns" in css


def test_workspace_links_to_the_editor_of_the_web():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")

    assert 'id="ws-open-web-editor"' in html
    assert "editor-of-the-web.html?repository=" in html


def test_existing_repository_engine_can_create_move_and_delete_folders(
    tmp_path, monkeypatch
):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")
    owner = _user(database)

    repository_id = repositories.create_repository(
        repositories.RepositoryCreate(name="web-editor-test"),
        owner,
    ).id

    repositories.write_file(
        repository_id,
        repositories.FileWriteRequest(
            path="docs/new-folder/.gitkeep",
            content="",
            branch="main",
            commit_message="Create folder docs/new-folder",
        ),
        owner,
    )
    root = repositories._repo_path(repository_id)
    assert (root / "docs" / "new-folder").is_dir()

    repositories.move_file(
        repository_id,
        repositories.FileMoveRequest(
            source_path="docs/new-folder",
            destination_path="guides/renamed-folder",
            branch="main",
            commit_message="Move folder",
        ),
        owner,
    )
    assert not (root / "docs" / "new-folder").exists()
    assert (root / "guides" / "renamed-folder" / ".gitkeep").is_file()

    repositories.delete_file(
        repository_id,
        repositories.FileDeleteRequest(
            path="guides/renamed-folder",
            branch="main",
            commit_message="Delete folder",
        ),
        owner,
    )
    assert not (root / "guides" / "renamed-folder").exists()
