import hashlib
from pathlib import Path

import httpx
import pytest

from amoscloud_ai.bundles_host import create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_bundle_upload_catalog_and_verified_download(monkeypatch, tmp_path):
    monkeypatch.setenv("AMOSCLAUD_BUNDLE_ROOT", str(tmp_path / "bundles"))
    monkeypatch.setenv("AMOSCLAUD_BUNDLES_API_KEY", "amos_bundle_test_key")
    content = b"amosclaud portable bundle\n"
    headers = {"Authorization": "Bearer amos_bundle_test_key"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="https://bundle.test"
    ) as client:
        assert (await client.get("/api/v1/bundles/health")).status_code == 200
        assert (await client.get("/api/v1/bundles")).status_code == 401
        created = await client.post(
            "/api/v1/bundles",
            headers=headers,
            data={"version": "1.2.3", "platform": "linux-x86_64", "channel": "stable"},
            files={"file": ("Amosclaud-Server.tar.gz", content, "application/gzip")},
        )
        assert created.status_code == 201
        metadata = created.json()
        assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
        assert metadata["bundle_id"] == "amosclaud-1.2.3-linux-x86_64-stable"

        catalog = await client.get("/api/v1/bundles", headers={"X-API-Key": "amos_bundle_test_key"})
        assert catalog.json()["count"] == 1
        download = await client.get(
            f'/api/v1/bundles/{metadata["bundle_id"]}/download', headers=headers
        )
        assert download.status_code == 200
        assert download.content == content
        assert download.headers["x-amosclaud-sha256"] == metadata["sha256"]


@pytest.mark.anyio
async def test_bundle_host_fails_closed_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AMOSCLAUD_BUNDLE_ROOT", str(tmp_path / "bundles"))
    for name in ("AMOSCLAUD_BUNDLES_API_KEY", "AMOSCLAUD_API_KEY", "EXTERNAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="https://bundle.test"
    ) as client:
        assert (await client.get("/api/v1/bundles")).status_code == 503


@pytest.mark.anyio
async def test_bundle_host_rejects_unsafe_and_duplicate_uploads(monkeypatch, tmp_path):
    monkeypatch.setenv("AMOSCLAUD_BUNDLE_ROOT", str(tmp_path / "bundles"))
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "amos_shared_key")
    headers = {"X-API-Key": "amos_shared_key"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="https://bundle.test"
    ) as client:
        unsafe = await client.post(
            "/api/v1/bundles",
            headers=headers,
            data={"version": "1.0.0", "platform": "linux"},
            files={"file": ("installer.exe", b"unsafe", "application/octet-stream")},
        )
        assert unsafe.status_code == 422
        request = {
            "headers": headers,
            "data": {"version": "1.0.0", "platform": "linux"},
            "files": {"file": ("Amosclaud.zip", b"bundle", "application/zip")},
        }
        assert (await client.post("/api/v1/bundles", **request)).status_code == 201
        assert (await client.post("/api/v1/bundles", **request)).status_code == 409


def test_bundle_documentation_dashboard_contains_safe_api_workflow():
    page = Path("web/bundles-api-docs.html").read_text(encoding="utf-8")
    assert "Bundles API Host" in page
    assert "/api/v1/bundles" in page
    assert "X-Amosclaud-SHA256" in page
    assert "localStorage" not in page
