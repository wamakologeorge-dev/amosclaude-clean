"""Integration tests for organization-identity auth flows."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Response

from amoscloud_ai.api.routes import auth, organization_identity as oi

_PWD = "test-password-123"
_PWD2 = "other-password-456"


@pytest.fixture()
def org_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up an isolated database for organization identity tests."""
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", db_path)
    monkeypatch.setattr(oi, "DB_PATH", db_path)
    return db_path


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_creates_owner_and_returns_recovery_codes(org_db):
    response = Response()
    result = oi.register(
        oi.OrganizationRegistration(
            organization_id="12345",
            organization_name="Acme Corp",
            username="admin1",
            password="test-password-123",
        ),
        response,
    )
    assert result["organization_id"] == "12345"
    assert result["username"] == "admin1"
    assert result["role"] == "owner"
    assert len(result["recovery_codes"]) == 3
    assert "amos_session=" in response.headers.get("set-cookie", "")


def test_register_rejects_duplicate_org_id(org_db):
    oi.register(
        oi.OrganizationRegistration(
            organization_id="11111",
            organization_name="First",
            username="user1",
            password="test-password-123",
        ),
        Response(),
    )
    with pytest.raises(Exception) as exc_info:
        oi.register(
            oi.OrganizationRegistration(
                organization_id="11111",
                organization_name="Second",
                username="user2",
                password="test-password-123",
            ),
            Response(),
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_with_username(org_db):
    oi.register(
        oi.OrganizationRegistration(
            organization_id="22222",
            organization_name="TestOrg",
            username="testuser",
            password="test-password-123",
        ),
        Response(),
    )
    response = Response()
    result = oi.login(
        oi.OrganizationLogin(
            organization_id="22222",
            username_or_member_id="testuser",
            password="test-password-123",
        ),
        response,
    )
    assert result["username"] == "testuser"
    assert result["role"] == "owner"
    assert "amos_session=" in response.headers.get("set-cookie", "")


def test_login_with_member_id(org_db):
    reg = oi.register(
        oi.OrganizationRegistration(
            organization_id="33333",
            organization_name="TestOrg",
            username="member1",
            password="test-password-123",
        ),
        Response(),
    )
    response = Response()
    result = oi.login(
        oi.OrganizationLogin(
            organization_id="33333",
            username_or_member_id=reg["member_id"],
            password="test-password-123",
        ),
        response,
    )
    assert result["member_id"] == reg["member_id"]


def test_login_invalid_password(org_db):
    oi.register(
        oi.OrganizationRegistration(
            organization_id="44444",
            organization_name="TestOrg",
            username="someone",
            password="test-password-123",
        ),
        Response(),
    )
    with pytest.raises(Exception) as exc_info:
        oi.login(
            oi.OrganizationLogin(
                organization_id="44444",
                username_or_member_id="someone",
                password="completely-wrong-pw",
            ),
            Response(),
        )
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Join code and join flow
# ---------------------------------------------------------------------------


def _register_and_get_session(org_db, org_id, username):
    """Register and return session cookie value."""
    response = Response()
    oi.register(
        oi.OrganizationRegistration(
            organization_id=org_id,
            organization_name="JoinOrg",
            username=username,
            password="test-password-123",
        ),
        response,
    )
    cookie = response.headers["set-cookie"]
    token = cookie.split("amos_session=")[1].split(";")[0]
    return token


def test_join_code_and_join_flow(org_db):
    token = _register_and_get_session(org_db, "55555", "owner1")
    user = auth.get_user_from_session(token)

    code_result = oi.create_join_code(
        "55555",
        oi.JoinCodeRequest(expires_minutes=30, uses=1),
        user,
    )
    assert "access_code" in code_result

    response = Response()
    join_result = oi.join(
        oi.OrganizationJoin(
            organization_id="55555",
            access_code=code_result["access_code"],
            username="joiner1",
            password="test-password-123",
        ),
        response,
    )
    assert join_result["role"] == "developer"
    assert join_result["username"] == "joiner1"
    assert len(join_result["recovery_codes"]) == 3


def test_single_use_join_code_exhausted(org_db):
    token = _register_and_get_session(org_db, "56789", "owner2")
    user = auth.get_user_from_session(token)

    code_result = oi.create_join_code(
        "56789",
        oi.JoinCodeRequest(expires_minutes=30, uses=1),
        user,
    )
    oi.join(
        oi.OrganizationJoin(
            organization_id="56789",
            access_code=code_result["access_code"],
            username="joiner2",
            password="test-password-123",
        ),
        Response(),
    )
    with pytest.raises(Exception) as exc_info:
        oi.join(
            oi.OrganizationJoin(
                organization_id="56789",
                access_code=code_result["access_code"],
                username="joiner3",
                password="test-password-123",
            ),
            Response(),
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_recovery_resets_password_and_invalidates_sessions(org_db):
    response = Response()
    reg = oi.register(
        oi.OrganizationRegistration(
            organization_id="66666",
            organization_name="RecOrg",
            username="recuser",
            password="test-password-123",
        ),
        response,
    )
    code = reg["recovery_codes"][0]
    result = oi.recover(
        oi.RecoveryRequest(
            organization_id="66666",
            username_or_member_id="recuser",
            recovery_code=code,
            new_password="brand-new-password1",
        ),
    )
    assert result["password_reset"] is True
    assert "replacement_recovery_code" in result

    # Old session should be invalidated
    old_token = response.headers["set-cookie"].split("amos_session=")[1].split(";")[0]
    assert auth.get_user_from_session(old_token) is None

    # Can login with new password
    oi.login(
        oi.OrganizationLogin(
            organization_id="66666",
            username_or_member_id="recuser",
            password="brand-new-password1",
        ),
        Response(),
    )


def test_recovery_code_cannot_be_reused(org_db):
    reg = oi.register(
        oi.OrganizationRegistration(
            organization_id="67890",
            organization_name="RecOrg2",
            username="recuser2",
            password="test-password-123",
        ),
        Response(),
    )
    code = reg["recovery_codes"][0]
    oi.recover(
        oi.RecoveryRequest(
            organization_id="67890",
            username_or_member_id="recuser2",
            recovery_code=code,
            new_password="new-password-one1",
        ),
    )
    with pytest.raises(Exception) as exc_info:
        oi.recover(
            oi.RecoveryRequest(
                organization_id="67890",
                username_or_member_id="recuser2",
                recovery_code=code,
                new_password="new-password-two2",
            ),
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


def test_owner_can_revoke_member(org_db):
    token = _register_and_get_session(org_db, "77777", "owner3")
    owner_user = auth.get_user_from_session(token)

    code_result = oi.create_join_code(
        "77777",
        oi.JoinCodeRequest(expires_minutes=30, uses=1),
        owner_user,
    )
    join_result = oi.join(
        oi.OrganizationJoin(
            organization_id="77777",
            access_code=code_result["access_code"],
            username="target1",
            password="test-password-123",
        ),
        Response(),
    )
    member_number = join_result["member_id"].split("-")[1]

    response = Response()
    oi.remove_member("77777", member_number, response, owner_user)
    assert response.status_code == 204


def test_cannot_remove_final_owner(org_db):
    token = _register_and_get_session(org_db, "88888", "solo_owner")
    owner_user = auth.get_user_from_session(token)

    memberships = oi.current(owner_user)
    member_number = memberships[0]["member_id"].split("-")[1]

    with pytest.raises(Exception) as exc_info:
        oi.remove_member("88888", member_number, Response(), owner_user)
    assert exc_info.value.status_code == 409
    assert "final owner" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# Identifier change
# ---------------------------------------------------------------------------


def test_owner_can_change_organization_id(org_db):
    token = _register_and_get_session(org_db, "99999", "idowner")
    owner_user = auth.get_user_from_session(token)

    result = oi.change_identifier(
        "99999",
        oi.OrganizationIdentifierChange(organization_id="98765"),
        owner_user,
    )
    assert result["previous_organization_id"] == "99999"
    assert result["organization_id"] == "98765"


def test_non_owner_cannot_change_identifier(org_db):
    token = _register_and_get_session(org_db, "10101", "idowner2")
    owner_user = auth.get_user_from_session(token)

    code_result = oi.create_join_code(
        "10101",
        oi.JoinCodeRequest(expires_minutes=30, uses=1),
        owner_user,
    )
    oi.join(
        oi.OrganizationJoin(
            organization_id="10101",
            access_code=code_result["access_code"],
            username="dev1",
            password="test-password-123",
        ),
        Response(),
    )
    resp2 = Response()
    oi.login(
        oi.OrganizationLogin(
            organization_id="10101",
            username_or_member_id="dev1",
            password="test-password-123",
        ),
        resp2,
    )
    dev_token = resp2.headers["set-cookie"].split("amos_session=")[1].split(";")[0]
    dev_user = auth.get_user_from_session(dev_token)

    with pytest.raises(Exception) as exc_info:
        oi.change_identifier(
            "10101",
            oi.OrganizationIdentifierChange(organization_id="20202"),
            dev_user,
        )
    assert exc_info.value.status_code == 403
