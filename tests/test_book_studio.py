from __future__ import annotations

import json
from pathlib import Path

import pytest

from amoscloud_ai.book import AmosclaudBook, BookError
from amoscloud_ai.book_studio import save_chapter, studio_tool_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOK_ROOT = REPO_ROOT / ".Amosclaud" / "book"
WEB_STUDIO = REPO_ROOT / "web" / "amosclaud-book-studio.html"
WEB_READER = REPO_ROOT / "web" / "amosclaud-book.html"


def _copy_book(tmp_path: Path) -> AmosclaudBook:
    root = tmp_path / "book"
    (root / "chapters").mkdir(parents=True)
    for name in ["book.manifest.json", "capabilities.json", "changes.jsonl", "next-task.json"]:
        (root / name).write_bytes((BOOK_ROOT / name).read_bytes())
    for chapter in (BOOK_ROOT / "chapters").glob("*.md"):
        (root / "chapters" / chapter.name).write_bytes(chapter.read_bytes())
    return AmosclaudBook(root)


def test_studio_catalog_reuses_word_graphics_and_3d_contracts() -> None:
    catalog = studio_tool_catalog()

    assert catalog["surface"] == "Amosclaud Book Studio"
    assert "paint-canvas" in catalog["tabs"]["graphics"]
    assert "agent-workstation-scene" in catalog["tabs"]["3d"]
    assert "Markdown" in catalog["canonical_format"]
    assert "visual editor state must never be the only source of meaning" in catalog["agent_rule"]


def test_studio_page_exposes_word_style_ribbon_and_existing_3d_loader() -> None:
    studio = WEB_STUDIO.read_text(encoding="utf-8")
    reader = WEB_READER.read_text(encoding="utf-8")

    for tab in ["Home", "Insert", "Design", "Graphics", "3D", "Agent Source"]:
        assert f">{tab}<" in studio
    assert "Paint / Draw" in studio
    assert "/static/agent-3d-loader.js" in studio
    assert ":::amosclaud-3d" in studio
    assert "Book Studio" in reader
    assert "data-book-3d" in reader


def test_book_studio_saves_structured_visual_directives(tmp_path: Path) -> None:
    book = _copy_book(tmp_path)
    source = """# Visual chapter

This chapter has a diagram and a 3D scene.

:::amosclaud-graphic kind=\"roadmap\" title=\"Delivery roadmap\"

:::amosclaud-3d scene=\"agent-workstation\" caption=\"Autonomous developer workstation\"
"""

    result = save_chapter(
        book,
        chapter_id="01",
        content=source,
        actor="owner",
        summary="Add visual directives",
    )

    saved = book.chapter("01")["content"]
    assert ":::amosclaud-graphic" in saved
    assert ":::amosclaud-3d" in saved
    assert result["chapter_id"] == "01"
    assert len(result["sha256"]) == 64
    assert (book.runtime_path / "studio.jsonl").exists()


def test_book_studio_blocks_probable_secret_without_storing_value(tmp_path: Path) -> None:
    book = _copy_book(tmp_path)
    candidate = "sk-" + "Q7mP9rT2vW4xY6zA8bC1dE3fG5hJ7kL9"
    source = f'# Unsafe\n\nOPENAI_API_KEY = "{candidate}"\n'

    with pytest.raises(BookError, match="credential-like material"):
        save_chapter(
            book,
            chapter_id="01",
            content=source,
            actor="owner",
            summary="Unsafe test",
        )

    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in book.root.rglob("*")
        if path.is_file()
    )
    assert candidate not in stored


def test_manifest_defines_book_as_public_product_not_private_security_tool() -> None:
    manifest = json.loads((BOOK_ROOT / "book.manifest.json").read_text(encoding="utf-8"))
    contract = manifest["product_contract"]

    assert contract["public_reading"] is True
    assert contract["human_readable"] is True
    assert contract["agent_readable"] is True
    assert contract["private_security_tool"] is False
