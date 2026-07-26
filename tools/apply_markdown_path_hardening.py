"""Correct the Markdown path containment integration and add coverage."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected one marker in {relative}, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    '''        target = _repo_target_path(repository_id, relative)
        target = (repo_root / relative).resolve()
        try:
            target.relative_to(repo_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid file path") from exc
''',
    '''        target = _repo_target_path(repository_id, relative)
''',
)

replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    '''    if not media_type:
        target = _repo_target_path(repository_id, relative)
''',
    '''    if not media_type:
        raise HTTPException(status_code=415, detail="Inline media type is not allowed")
''',
)

replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    '''        repository_root = _repo_path(repository_id).resolve()
        target = (repository_root / relative).resolve(strict=False)
        try:
            target.relative_to(repository_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid file path") from exc
''',
    '''        target = _repo_target_path(repository_id, relative)
''',
)

symlink_test = '''

def test_markdown_and_media_endpoints_reject_symlinks_outside_repository(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="contained-project"), owner
    ).id
    repo = repositories._open(rid)
    root = repositories._repo_path(rid)
    outside_markdown = tmp_path / "outside.md"
    outside_image = tmp_path / "outside.png"
    outside_markdown.write_text("# Private\\n", encoding="utf-8")
    outside_image.write_bytes(b"\\x89PNG\\r\\n\\x1a\\nPRIVATE")
    (root / "escape.md").symlink_to(outside_markdown)
    (root / "escape.png").symlink_to(outside_image)
    repo.index.add(["escape.md", "escape.png"])
    repo.index.commit("Add path-containment fixtures")

    markdown = _get(token, f"/api/v1/repositories/{rid}/markdown?path=escape.md")
    media = _get(token, f"/api/v1/repositories/{rid}/raw?path=escape.png")

    assert markdown.status_code == 422
    assert media.status_code == 422

'''

replace_once(
    "tests/test_amosclaud_markdown_service.py",
    "\ndef test_workspace_loads_backend_markdown_service_and_repository_overview():\n",
    symlink_test
    + "\ndef test_workspace_loads_backend_markdown_service_and_repository_overview():\n",
)
