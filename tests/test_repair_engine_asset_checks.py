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
