import asyncio
import httpx

from amoscloud_ai.api.routes import auth, downloads
from amoscloud_ai.main import create_app


async def _request(path: str, follow_redirects: bool = False):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="https://amosclaud.test",
        follow_redirects=follow_redirects,
    ) as client:
        return await client.get(path)


def request(path: str):
    return asyncio.run(_request(path))


def test_download_manifest_and_allowlisted_redirect(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "downloads.db"
    monkeypatch.setenv("AMOSCLAUD_RELEASE_REPOSITORY", "owner/project")
    manifest = request("/api/v1/downloads/latest")
    assert manifest.status_code == 200
    assert manifest.json()["artifacts"]["windows"]["filename"].endswith(".zip")

    response = request("/api/v1/downloads/windows")
    assert response.status_code == 307
    assert response.headers["location"] == (
        "https://github.com/owner/project/releases/latest/download/Amosclaud-Server.zip"
    )
    assert request("/api/v1/downloads/not-a-platform").status_code == 404


def test_download_metrics_are_aggregate_and_admin_only(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "downloads.db"
    monkeypatch.setenv("AMOSCLAUD_RELEASE_REPOSITORY", "owner/project")
    request("/api/v1/downloads/linux")
    assert request("/api/v1/downloads/metrics/summary").status_code == 403
    monkeypatch.setattr(downloads, "get_user_from_session", lambda _token: {"is_admin": 1})
    metrics = request("/api/v1/downloads/metrics/summary")
    assert metrics.json() == {"downloads": {"linux": 1}}
