"""Regression contracts for the real Editor of the Web experience."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_workspace_edit_button_opens_the_full_editor() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")

    assert 'id="ws-open-web-editor"' in html
    assert "Open full editor" in html
    assert "editor-of-the-web.html?repository=" in html
    assert "openFullEditor" in html
    assert "ws-mode-edit" in html
    assert "event.stopImmediatePropagation()" in html
    assert "url.searchParams.set('mode', 'edit')" in html


def test_full_editor_opens_readme_and_selected_files() -> None:
    source = (WEB / "editor-autostart.js").read_text(encoding="utf-8")

    assert "params.get('path') || 'README.md'" in source
    assert "data-open-path" in source
    assert "requestedMode === 'edit'" in source
    assert "editButton.click()" in source
    assert "eow-editor" in source


def test_editor_pages_load_mobile_editing_overrides() -> None:
    workspace = (WEB / "workspace.html").read_text(encoding="utf-8")
    editor = (WEB / "editor-of-the-web.html").read_text(encoding="utf-8")
    css = (WEB / "editor-experience.css").read_text(encoding="utf-8")

    assert "/static/editor-experience.css" in workspace
    assert "/static/editor-experience.css" in editor
    assert "/static/editor-autostart.js" in editor
    assert "README.md opens automatically" in editor
    assert "min-height: 62vh" in css
    assert "100dvh" in css
    assert "body.eow-focus-mode" in css


def test_full_editor_keeps_real_commit_and_repository_controls() -> None:
    html = (WEB / "editor-of-the-web.html").read_text(encoding="utf-8")
    source = (WEB / "editor-of-the-web.js").read_text(encoding="utf-8")

    for element_id in (
        'id="eow-tree"',
        'id="eow-editor"',
        'id="eow-save"',
        'id="eow-new-file"',
        'id="eow-new-folder"',
        'id="eow-rename"',
        'id="eow-delete"',
    ):
        assert element_id in html

    assert "method: 'PUT'" in source
    assert "method: 'DELETE'" in source
    assert "/move" in source
    assert "commit_message" in source
