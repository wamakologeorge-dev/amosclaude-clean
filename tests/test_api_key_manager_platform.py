from api_key_manager import auth, crud, models, schemas
from api_key_manager.database import SessionLocal, ensure_schema
from api_key_manager.main import app
from amosclaud_platform.control import PlatformControl


def test_credential_routes_are_registered():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/health" in paths
    assert "/token" in paths
    assert "/api-keys/" in paths
    assert "/api-keys/validate" in paths
    assert "/audit-events" in paths


def test_scope_contract_rejects_unknown_permissions():
    try:
        schemas.ApiKeyCreate(scopes=["secrets:read"])
    except ValueError as exc:
        assert "Unsupported API-key scopes" in str(exc)
    else:
        raise AssertionError("Unknown API-key scope was accepted")


def test_scoped_key_records_audit_evidence(tmp_path, monkeypatch):
    database_path = tmp_path / "keys.db"
    monkeypatch.setenv("API_KEY_DATABASE_URL", f"sqlite:///{database_path}")

    # The module-level engine is intentionally stable, so this test validates
    # the model/CRUD contract against its configured isolated CI database.
    ensure_schema()
    db = SessionLocal()
    try:
        plain_key = auth.generate_api_key_string()
        record = crud.create_api_key(
            db,
            schemas.ApiKeyCreate(
                description="fixer",
                scopes=["ci:run", "jobs:update", "repositories:read"],
            ),
            plain_key,
            auth.api_key_lookup_prefix(plain_key),
            actor="owner",
        )
        assert crud.scopes_for(record) == ["ci:run", "jobs:update", "repositories:read"]
        assert record.created_by == "owner"
        events = crud.list_audit_events(db)
        assert events[0].event == "created"
        assert events[0].key_id == record.id
    finally:
        db.query(models.ApiKeyAuditEvent).delete()
        db.query(models.ApiKey).delete()
        db.commit()
        db.close()


def test_platform_doctor_lists_credential_authority(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = PlatformControl(repository_root=tmp_path / "repositories").doctor().as_dict()
    names = {item["name"] for item in report["services"]}
    assert "api_key_manager" in names
    assert "credential_database" in names
    assert "credential_jwt_secret" in names
    assert "credential_admin" in names
