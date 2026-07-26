"""Regression tests for the production Docker deployment configuration."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_only_reverse_proxy_publishes_host_ports() -> None:
    services = COMPOSE["services"]

    assert "ports" not in services["amoscloud_api"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis"]
    assert set(services["caddy"]["ports"]) == {
        "80:80",
        "443:443",
        "443:443/udp",
    }


def test_backend_services_use_internal_network_and_healthchecks() -> None:
    services = COMPOSE["services"]

    assert COMPOSE["networks"]["backend"]["internal"] is True
    assert services["postgres"]["networks"] == ["backend"]
    assert services["redis"]["networks"] == ["backend"]
    assert set(services["amoscloud_api"]["networks"]) == {"edge", "backend"}

    for name in ("postgres", "redis", "amoscloud_api", "caddy"):
        assert "healthcheck" in services[name]
        assert services[name]["restart"] == "unless-stopped"


def test_sensitive_values_are_file_mounted_secrets() -> None:
    services = COMPOSE["services"]
    api_environment = services["amoscloud_api"]["environment"]
    secret_names = {
        "postgres_password",
        "redis_password",
        "secret_key",
        "amosclaud_master_key",
        "metrics_token",
        "github_token_encryption_key",
    }

    assert secret_names.issubset(COMPOSE["secrets"])
    assert secret_names.issubset(set(services["amoscloud_api"]["secrets"]))

    for name, definition in COMPOSE["secrets"].items():
        assert definition["file"] == f"./secrets/{name}"

    assert "SECRET_KEY" not in api_environment
    assert "POSTGRES_PASSWORD" not in api_environment
    assert "REDIS_PASSWORD" not in api_environment
    assert api_environment["SECRET_KEY_FILE"] == "/run/secrets/secret_key"
    assert api_environment["POSTGRES_PASSWORD_FILE"] == (
        "/run/secrets/postgres_password"
    )
    assert api_environment["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"


def test_caddy_owns_tls_and_proxies_only_to_internal_api() -> None:
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert "{$ACME_EMAIL}" in caddyfile
    assert "{$APEX_DOMAIN}" in caddyfile
    assert "{$PRIMARY_DOMAIN}" in caddyfile
    assert "reverse_proxy amoscloud_api:8000" in caddyfile
    assert "Strict-Transport-Security" in caddyfile
    assert "redir https://{$PRIMARY_DOMAIN}{uri} permanent" in caddyfile


def test_production_environment_example_contains_no_secret_assignments() -> None:
    example = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    active_lines = {
        line.strip()
        for line in example.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    forbidden_prefixes = (
        "SECRET_KEY=",
        "POSTGRES_PASSWORD=",
        "REDIS_PASSWORD=",
        "AMOSCLAUD_MASTER_KEY=",
        "AMOSCLAUD_METRICS_TOKEN=",
        "GITHUB_CLIENT_SECRET=",
        "GITHUB_TOKEN_ENCRYPTION_KEY=",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
    )

    assert not any(
        line.startswith(forbidden_prefixes) for line in active_lines
    )


def test_entrypoint_builds_authenticated_service_urls() -> None:
    entrypoint = (ROOT / "docker/production-entrypoint.sh").read_text(
        encoding="utf-8"
    )

    assert "Required production secret" in entrypoint
    assert "postgresql+psycopg2://" in entrypoint
    assert "redis://:" in entrypoint
    assert "--proxy-headers" in entrypoint
    assert "--forwarded-allow-ips" in entrypoint
