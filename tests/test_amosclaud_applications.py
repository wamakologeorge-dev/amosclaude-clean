from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes import applications, organizations


def test_application_scope_contract_has_agent_and_spacecodeme() -> None:
    assert "agent:invoke" in applications.SCOPES
    assert "spacecodeme:use" in applications.SCOPES
    assert "deployment:production" in applications.SCOPES


def test_application_scope_contract_rejects_unknown_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        applications._validate_scopes(["agent:invoke", "root:everything"])
    assert exc.value.status_code == 422


def test_application_routes_are_mounted_on_organization_surface() -> None:
    keys = {
        (getattr(route, "path", ""), method)
        for route in organizations.router.routes
        for method in (getattr(route, "methods", None) or [])
    }
    assert ("/applications", "POST") in keys
    assert ("/applications", "GET") in keys
    assert ("/organizations/{organization_id}/applications/{application_id}/install", "POST") in keys
    assert ("/organizations/{organization_id}/application-installations/{installation_id}/credentials", "POST") in keys


def test_two_organizations_get_independent_installations(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "applications.db"
    monkeypatch.setattr(organizations, "DB_PATH", db_path)

    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )"""
        )
        db.execute("INSERT INTO users(id,name,email,is_admin) VALUES (1,'Developer','dev@example.test',1)")
        db.commit()

    user = {"id": 1, "name": "Developer", "email": "dev@example.test", "is_admin": 1}
    first = organizations.create_organization(
        organizations.OrganizationCreate(name="First Org", slug="first-org"), user=user
    )
    second = organizations.create_organization(
        organizations.OrganizationCreate(name="Second Org", slug="second-org"), user=user
    )
    app = applications.create_application(
        applications.ApplicationCreate(
            name="Shared Builder",
            requested_scopes=["repository:read", "agent:invoke"],
            visibility="public",
        ),
        user=user,
    )

    install_one = applications.install_application(
        first["id"],
        app["id"],
        applications.ApplicationInstall(scopes=["repository:read"]),
        user=user,
    )
    install_two = applications.install_application(
        second["id"],
        app["id"],
        applications.ApplicationInstall(scopes=["agent:invoke"]),
        user=user,
    )

    assert install_one["id"] != install_two["id"]
    assert install_one["organization_id"] != install_two["organization_id"]
    assert install_one["scopes"] == ["repository:read"]
    assert install_two["scopes"] == ["agent:invoke"]

    applications.revoke_installation(first["id"], install_one["id"], user=user)
    remaining = applications.list_installed_applications(second["id"], user=user)
    assert [item["id"] for item in remaining] == [install_two["id"]]
