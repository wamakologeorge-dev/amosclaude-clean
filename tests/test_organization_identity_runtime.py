from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException, Response

from amoscloud_ai.api.routes import auth, organization_identity


def _token(response: Response) -> str:
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[auth.SESSION_COOKIE].value


@pytest.fixture()
def isolated_identity_db(tmp_path, monkeypatch):
    path = tmp_path / "organization-auth.db"
    monkeypatch.setattr(auth, "DB_PATH", path)
    monkeypatch.setattr(organization_identity, "DB_PATH", path)
    return path


def _register_owner() -> tuple[dict, Response]:
    response = Response()
    result = organization_identity.register(
        organization_identity.OrganizationRegistration(
            organization_id="11111",
            organization_name="Amosclaud Builders",
            username="johnM",
            password="correct-horse-battery-staple",
        ),
        response,
    )
    return result, response


def _owner_user(response: Response):
    user = auth.get_user_from_session(_token(response))
    assert user is not None
    return user


def test_registration_login_and_recovery_invalidate_old_sessions(
    isolated_identity_db,
) -> None:
    owner, owner_response = _register_owner()

    assert owner["organization_id"] == "11111"
    assert owner["member_id"].startswith("11111-")
    assert len(owner["recovery_codes"]) == 3

    login_response = Response()
    organization_identity.login(
        organization_identity.OrganizationLogin(
            organization_id="11111",
            username_or_member_id=owner["member_id"],
            password="correct-horse-battery-staple",
        ),
        login_response,
    )
    old_token = _token(login_response)
    assert auth.get_user_from_session(old_token) is not None

    recovered = organization_identity.recover(
        organization_identity.RecoveryRequest(
            organization_id="11111",
            username_or_member_id="johnM",
            recovery_code=owner["recovery_codes"][0],
            new_password="a-new-strong-password",
        )
    )

    assert recovered["password_reset"] is True
    assert recovered["replacement_recovery_code"]
    assert auth.get_user_from_session(old_token) is None

    new_login_response = Response()
    organization_identity.login(
        organization_identity.OrganizationLogin(
            organization_id="11111",
            username_or_member_id="johnM",
            password="a-new-strong-password",
        ),
        new_login_response,
    )
    assert auth.get_user_from_session(_token(new_login_response)) is not None
    assert auth.get_user_from_session(_token(owner_response)) is None


def test_one_use_join_code_cannot_create_two_members(isolated_identity_db) -> None:
    _, owner_response = _register_owner()
    owner_user = _owner_user(owner_response)
    invitation = organization_identity.create_join_code(
        "11111",
        organization_identity.JoinCodeRequest(expires_minutes=30, uses=1),
        owner_user,
    )

    joined = organization_identity.join(
        organization_identity.OrganizationJoin(
            organization_id="11111",
            access_code=invitation["access_code"],
            username="sameG",
            password="another-strong-password",
        ),
        Response(),
    )
    assert joined["member_id"].startswith("11111-")

    with pytest.raises(HTTPException) as error:
        organization_identity.join(
            organization_identity.OrganizationJoin(
                organization_id="11111",
                access_code=invitation["access_code"],
                username="thirdUser",
                password="a-third-strong-password",
            ),
            Response(),
        )
    assert error.value.status_code == 400


def test_owner_removes_member_and_member_cannot_sign_in(isolated_identity_db) -> None:
    _, owner_response = _register_owner()
    owner_user = _owner_user(owner_response)
    invitation = organization_identity.create_join_code(
        "11111",
        organization_identity.JoinCodeRequest(uses=1),
        owner_user,
    )
    joined = organization_identity.join(
        organization_identity.OrganizationJoin(
            organization_id="11111",
            access_code=invitation["access_code"],
            username="sameG",
            password="another-strong-password",
        ),
        Response(),
    )
    member_number = joined["member_id"].split("-", 1)[1]

    removal_response = Response()
    organization_identity.remove_member(
        "11111",
        member_number,
        removal_response,
        owner_user,
    )
    assert removal_response.status_code == 204

    with organization_identity._db() as db:
        disabled = db.execute(
            "SELECT password_hash FROM users WHERE name='sameG'"
        ).fetchone()
    assert disabled is not None
    assert disabled["password_hash"] is None

    with pytest.raises(HTTPException) as error:
        organization_identity.login(
            organization_identity.OrganizationLogin(
                organization_id="11111",
                username_or_member_id=joined["member_id"],
                password="another-strong-password",
            ),
            Response(),
        )
    assert error.value.status_code == 401


def test_owner_can_transfer_ownership_before_leaving(isolated_identity_db) -> None:
    owner, owner_response = _register_owner()
    owner_user = _owner_user(owner_response)
    invitation = organization_identity.create_join_code(
        "11111",
        organization_identity.JoinCodeRequest(uses=1),
        owner_user,
    )
    joined = organization_identity.join(
        organization_identity.OrganizationJoin(
            organization_id="11111",
            access_code=invitation["access_code"],
            username="nextOwner",
            password="next-owner-strong-password",
        ),
        Response(),
    )
    member_number = joined["member_id"].split("-", 1)[1]

    transfer = organization_identity.transfer_ownership(
        "11111",
        organization_identity.OwnershipTransfer(member_number=member_number),
        owner_user,
    )
    assert transfer["owner_member_id"] == joined["member_id"]

    with organization_identity._db() as db:
        roles = {
            row["username"]: row["role"]
            for row in db.execute("""SELECT username,role FROM organization_members
                   ORDER BY username""").fetchall()
        }
    assert roles[owner["username"]] == "admin"
    assert roles[joined["username"]] == "owner"


def test_backfill_runs_only_for_unapplied_schema_version(isolated_identity_db, monkeypatch) -> None:
    calls = 0
    original = organization_identity._backfill

    def counted_backfill(db):
        nonlocal calls
        calls += 1
        return original(db)

    monkeypatch.setattr(organization_identity, "_backfill", counted_backfill)
    with organization_identity._db():
        pass
    with organization_identity._db():
        pass
    assert calls == 1


def test_blank_organization_name_is_rejected(isolated_identity_db) -> None:
    with pytest.raises(HTTPException) as error:
        organization_identity.register(
            organization_identity.OrganizationRegistration(
                organization_id="11111",
                organization_name="  ",
                username="johnM",
                password="correct-horse-battery-staple",
            ),
            Response(),
        )
    assert error.value.status_code == 422
