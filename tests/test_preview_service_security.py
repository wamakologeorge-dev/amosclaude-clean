import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException


os.environ.setdefault("AMOSCLAUD_PREVIEW_SERVICE_KEY", "test-preview-key")
os.environ["AMOSCLAUD_PREVIEW_DATA"] = tempfile.mkdtemp(
    prefix="amosclaud-preview-tests-"
)

from preview_service.app import (  # noqa: E402
    SECURITY_HEADERS,
    _extract_static_site,
    _safe_member_path,
)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_static_preview_archive_is_extracted_without_execution(tmp_path: Path) -> None:
    destination = tmp_path / "site"
    _extract_static_site(
        _zip_bytes(
            {
                "index.html": b"<h1>Amosclaud</h1>",
                "assets/app.js": b"console.log('static')",
            }
        ),
        destination,
    )

    assert (destination / "index.html").is_file()
    assert (destination / "assets" / "app.js").is_file()


def test_preview_archive_path_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(HTTPException):
        _extract_static_site(
            _zip_bytes(
                {
                    "index.html": b"safe",
                    "../escape.html": b"unsafe",
                }
            ),
            tmp_path / "site",
        )


def test_preview_path_normalization_rejects_absolute_paths() -> None:
    with pytest.raises(HTTPException):
        _safe_member_path("/etc/passwd")


def test_preview_response_headers_block_embedding_and_capabilities() -> None:
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in SECURITY_HEADERS["Content-Security-Policy"]
    assert "camera=()" in SECURITY_HEADERS["Permissions-Policy"]


def test_preview_service_is_static_only_and_shell_free() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "preview_service" / "app.py").read_text(encoding="utf-8")
    dockerfile = (root / "preview_service" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "subprocess" not in source
    assert "shell=True" not in source
    assert 'CMD ["sh", "-c"' not in dockerfile
    assert 'CMD ["python", "-m", "preview_service.server"]' in dockerfile
