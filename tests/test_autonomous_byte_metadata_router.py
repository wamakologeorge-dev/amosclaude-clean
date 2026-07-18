from amoscloud_ai.autonomous.server.api.cb.router.byte import metadata
from amoscloud_ai.main import create_app
from amoscloud_ai.route_discovery import route_paths


def test_byte_metadata_router_is_registered():
    paths = route_paths(create_app().routes)
    base = "/api/v1/autonomous/server/api/cb/router/byte/metadata"
    assert base in paths
    assert f"{base}/{{filename}}" in paths


def test_byte_metadata_contract(monkeypatch):
    monkeypatch.setattr(metadata, "_require_identity", lambda request: {"id": 1})
    monkeypatch.setattr(
        metadata.store,
        "list",
        lambda: [
            {
                "filename": "routing-1.Amosclaud.bytes",
                "name": "routing",
                "version": "1",
                "byte_size": 128,
                "mapping_count": 2,
                "created_at": "2026-07-16T00:00:00+00:00",
            }
        ],
    )

    result = metadata.byte_metadata_index(request=object())
    assert result["contract"] == "amosclaud.autonomous.byte-metadata/v1"
    assert result["bundle_count"] == 1
    assert result["total_bytes"] == 128
    assert result["bundles"][0]["verified"] is True
