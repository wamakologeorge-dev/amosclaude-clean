from __future__ import annotations

from pathlib import Path

from amoscloud_ai.repair_engine import Doctor


def test_root_relative_web_routes_are_not_filesystem_escapes(tmp_path: Path) -> None:
    page = tmp_path / "web" / "index.html"
    page.parent.mkdir(parents=True)
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "style.css").write_text("body {}\n", encoding="utf-8")
    page.write_text(
        '<link rel="stylesheet" href="/static/style.css">\n'
        '<a href="/repositories">Repositories</a>\n'
        '<a href="/api/v1/github/connect">Connect</a>\n'
        '<a href="/">Home</a>\n',
        encoding="utf-8",
    )

    findings = Doctor(tmp_path).diagnose()

    assert not any(item.code == "asset-outside-root" for item in findings)
    assert not any(item.code == "missing-local-asset" for item in findings)


def test_fastapi_static_mount_resolves_assets_from_web_directory(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir(parents=True)
    (web / "style.css").write_text("body {}\n", encoding="utf-8")
    (web / "app.js").write_text("console.log('ok');\n", encoding="utf-8")
    (web / "manifest.webmanifest").write_text("{}\n", encoding="utf-8")
    (web / "index.html").write_text(
        '<link rel="manifest" href="/manifest.webmanifest">\n'
        '<link rel="stylesheet" href="/static/style.css">\n'
        '<script src="/static/app.js"></script>\n',
        encoding="utf-8",
    )

    findings = Doctor(tmp_path).diagnose()

    assert not any(item.code == "missing-local-asset" for item in findings)


def test_decorative_equals_line_is_not_a_merge_conflict(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        '"""\nService title\n========================================\n"""\n',
        encoding="utf-8",
    )

    findings = Doctor(tmp_path).diagnose()

    assert not any(item.code == "merge-conflict" for item in findings)


def test_real_merge_conflict_separator_is_critical(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "<<<<<<< HEAD\nleft = 1\n=======\nright = 2\n>>>>>>> feature\n",
        encoding="utf-8",
    )

    findings = Doctor(tmp_path).diagnose()

    assert any(item.code == "merge-conflict" for item in findings)


def test_relative_parent_path_that_leaves_repo_is_critical(tmp_path: Path) -> None:
    page = tmp_path / "web" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<script src="../../outside.js"></script>\n', encoding="utf-8")

    findings = Doctor(tmp_path).diagnose()

    assert any(item.code == "asset-outside-root" for item in findings)


def test_missing_root_relative_file_is_reported_as_missing_not_escape(tmp_path: Path) -> None:
    page = tmp_path / "web" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<script src="/static/missing.js"></script>\n', encoding="utf-8")

    findings = Doctor(tmp_path).diagnose()

    assert not any(item.code == "asset-outside-root" for item in findings)
    assert any(item.code == "missing-local-asset" for item in findings)
