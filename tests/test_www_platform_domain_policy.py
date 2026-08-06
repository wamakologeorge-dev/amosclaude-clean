from pathlib import Path

from amoscloud_ai.domain_policy import (
    WWW_PLATFORM_URL,
    enforce_platform_domain_policy,
)

ROOT = Path(__file__).resolve().parents[1]


def test_apex_configuration_is_normalised_to_the_www_platform(monkeypatch) -> None:
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

    assert __import__("os").environ["AMOSCLAUD_PUBLIC_URL"] == WWW_PLATFORM_URL
    assert (
        __import__("os").environ["GITHUB_ADMIN_CALLBACK_URL"]
        == "https://www.amosclaud.com/api/v1/auth/github/admin-callback"
    )
    assert (
        __import__("os").environ["GITHUB_REPOSITORY_CALLBACK_URL"]
        == "https://www.amosclaud.com/api/v1/github/callback"
    )
    assert __import__("os").environ["AUTH_COOKIE_DOMAIN"] == ""


def test_www_configuration_uses_host_only_session_cookies(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", "amosclaud.com")

    enforce_platform_domain_policy()

    assert __import__("os").environ["AUTH_COOKIE_DOMAIN"] == ""


def test_custom_self_hosted_domain_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://amos.example.net")
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", ".example.net")
    monkeypatch.delenv("GITHUB_ADMIN_CALLBACK_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY_CALLBACK_URL", raising=False)

    enforce_platform_domain_policy()

    environment = __import__("os").environ
    assert environment["AMOSCLAUD_PUBLIC_URL"] == "https://amos.example.net"
    assert environment["AUTH_COOKIE_DOMAIN"] == ".example.net"
    assert (
        environment["GITHUB_ADMIN_CALLBACK_URL"]
        == "https://amos.example.net/api/v1/auth/github/admin-callback"
    )
    assert (
        environment["GITHUB_REPOSITORY_CALLBACK_URL"]
        == "https://amos.example.net/api/v1/github/callback"
    )


def test_startup_applies_domain_policy_after_loading_dotenv() -> None:
    package_init = (ROOT / "amoscloud_ai" / "__init__.py").read_text(encoding="utf-8")

    assert package_init.index("load_dotenv(override=False)") < package_init.index(
        "enforce_platform_domain_policy()"
    )


def test_production_example_keeps_the_apex_platform_separate() -> None:
    production = (ROOT / ".env.production.example").read_text(encoding="utf-8")

    assert "PRIMARY_DOMAIN=www.amosclaud.com" in production
    assert "APEX_DOMAIN=\n" in production
    assert "AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com" in production
    assert "AUTH_COOKIE_DOMAIN=\n" in production
    assert (
        "GITHUB_REPOSITORY_CALLBACK_URL="
        "https://www.amosclaud.com/api/v1/github/callback"
    ) in production
