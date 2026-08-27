from __future__ import annotations

import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes.agent import _require_authority_scope, _require_mode_scope


def _authority_user(*scopes: str) -> dict:
    return {
        "id": 1,
        "_amosclaud_principal": {
            "scopes": list(scopes),
        },
    }


def test_authority_scope_helper_allows_matching_scope() -> None:
    _require_authority_scope(_authority_user("github:read"), "github:read")


def test_authority_scope_helper_rejects_missing_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _require_authority_scope(_authority_user("github:read"), "github:write")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["required_scope"] == "github:write"


def test_mode_scope_maps_build_and_deploy_permissions() -> None:
    _require_mode_scope(_authority_user("build"), "build")

    with pytest.raises(HTTPException) as exc_info:
        _require_mode_scope(_authority_user("build"), "deploy")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["required_scope"] == "deploy"


def test_legacy_and_session_users_keep_existing_behavior() -> None:
    _require_authority_scope({"id": 1}, "github:write")
    _require_mode_scope({"id": 1}, "fix")
