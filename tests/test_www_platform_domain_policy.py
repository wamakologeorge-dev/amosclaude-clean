import os
from pathlib import Path

from amoscloud_ai.domain_policy import (
    CANONICAL_PLATFORM_URL,
    enforce_platform_domain_policy,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CALLBACK = "https://amosclauds.com/api/v1/auth/github/admin-callback"


def test_apex_configuration_is_normalised_to_the_canonical_platform(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://amosclaud.com")
    monkeypatch.setenv(
        "GITHUB_ADMIN_CALLBACK_URL",
        "https://amosclaud.com/api/v1/auth/github/admin-callback",
    )
    monkeypatch.setenv(
        "GITHUB_REPOSITORY_CALLBACK_URL",
        "https://amosclaud.com/api/v1/github/callback",
    )
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", ".amosclaud.com")

    enforce_platform_domain_policy()

    assert os.environ["AMOSCLAUD_PUBLIC_URL"] == CANONICAL_PLATFORM_URL
    assert os.environ["GITHUB_ADMIN_CALLBACK_URL"] == CANONICAL_CALLBACK
    assert os.environ["GITHUB_REPOSITORY_CALLBACK_URL"] == CANONICAL_CALLBACK
    assert os.environ["AUTH_COOKIE_DOMAIN"] == ""


def test_legacy_www_configuration_is_normalised_forward(monkeypatch) -> None:
    """Anti-regression guarantee: a stale legacy env value must not drag the
    platform back. www.amosclaud.com is legacy and must normalise forward to
    the new canonical https://amosclauds.com, with host-only cookies."""
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", "amosclaud.com")

    enforce_platform_domain_policy()

    assert os.environ["AMOSCLAUD_PUBLIC_URL"] == CANONICAL_PLATFORM_URL
    assert os.environ["GITHUB_ADMIN_CALLBACK_URL"] == CANONICAL_CALLBACK
    assert os.environ["GITHUB_REPOSITORY_CALLBACK_URL"] == CANONICAL_CALLBACK
    assert os.environ["AUTH_COOKIE_DOMAIN"] == ""


def test_canonical_configuration_uses_host_only_session_cookies(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://amosclauds.com")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", "amosclauds.com")

    enforce_platform_domain_policy()

    assert os.environ["AUTH_COOKIE_DOMAIN"] == ""


def test_canonical_www_subdomain_normalises_to_bare_canonical_host(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclauds.com")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", "")

    enforce_platform_domain_policy()

    assert os.environ["AMOSCLAUD_PUBLIC_URL"] == CANONICAL_PLATFORM_URL
    assert os.environ["AUTH_COOKIE_DOMAIN"] == ""


def test_custom_self_hosted_domain_uses_one_callback(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://amos.example.net")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", ".example.net")
    monkeypatch.delenv("GITHUB_ADMIN_CALLBACK_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY_CALLBACK_URL", raising=False)

    enforce_platform_domain_policy()

    expected = "https://amos.example.net/api/v1/auth/github/admin-callback"
    assert os.environ["AMOSCLAUD_PUBLIC_URL"] == "https://amos.example.net"
    assert os.environ["AUTH_COOKIE_DOMAIN"] == ".example.net"
    assert os.environ["GITHUB_ADMIN_CALLBACK_URL"] == expected
    assert os.environ["GITHUB_REPOSITORY_CALLBACK_URL"] == expected


def test_startup_applies_domain_policy_after_loading_dotenv() -> None:
    package_init = (ROOT / "amoscloud_ai" / "__init__.py").read_text(encoding="utf-8")

    assert package_init.index("load_dotenv(override=False)") < package_init.index(
        "enforce_platform_domain_policy()"
    )


def test_production_example_keeps_the_legacy_platform_separate() -> None:
    production = (ROOT / ".env.production.example").read_text(encoding="utf-8")

    assert "PRIMARY_DOMAIN=amosclauds.com" in production
    assert "APEX_DOMAIN=\n" in production
    assert "AMOSCLAUD_PUBLIC_URL=https://amosclauds.com" in production
    assert "AUTH_COOKIE_DOMAIN=\n" in production
    assert f"GITHUB_ADMIN_CALLBACK_URL={CANONICAL_CALLBACK}" in production
    assert f"GITHUB_REPOSITORY_CALLBACK_URL={CANONICAL_CALLBACK}" in production
