from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes import applications, organizations


def test_scope_catalog_contains_agent_and_spacecodeme() -> None:
    assert "agent:invoke" in applications.SCOPE_CATALOG
    assert "spacecodeme:use" in applications.SCOPE_CATALOG
    assert "deployments:production" in applications.SCOPE_CATALOG


def test_normalize_scopes_deduplicates_and_sorts() -> None:
    assert applications._normalize_scopes(
        ["terminal:execute", "agent:invoke", "terminal:execute"]
    ) == ["agent:invoke", "terminal:execute"]


def test_unknown_scope_is_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        applications._normalize_scopes(["root:everything"])
    assert error.value.status_code == 422
    assert error.value.detail == {"unknown_scopes": ["root:everything"]}


def test_application_token_hash_is_one_way_digest() -> None:
    raw = "amos_app_example-secret"
    digest = applications._hash_token(raw)
    assert raw not in digest
    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(digest) == 64


def test_application_routes_are_mounted_on_canonical_organization_router() -> None:
    paths = {getattr(route, "path", "") for route in organizations.router.routes}
    assert "/integrations/scopes" in paths
    assert "/organizations/{organization_id}/applications" in paths
    assert "/applications/{application_id}/installations" in paths
    assert "/installations/{installation_id}/tokens" in paths
