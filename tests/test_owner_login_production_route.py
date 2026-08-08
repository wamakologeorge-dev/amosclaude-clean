from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_railway_starts_owner_enabled_application() -> None:
    railway = _read("railway.toml")
    assert "uvicorn amoscloud_ai.production_app:app" in railway
    assert "uvicorn amoscloud_ai.owner_app:app" not in railway
    assert "uvicorn amoscloud_ai.main:app" not in railway


def test_owner_application_exposes_root_and_legacy_api_paths() -> None:
    production_app = _read("amoscloud_ai/production_app.py")
    assert "app.include_router(owner_access_gateway.router)" in production_app
    assert 'prefix="/api/v1"' in production_app

    owner_app = _read("amoscloud_ai/owner_app.py")
    assert '"/auth/github/admin-login"' in owner_app
    assert '"/api/v1/auth/github/admin-login"' in owner_app
