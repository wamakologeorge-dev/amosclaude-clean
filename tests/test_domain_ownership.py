from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_URL = "https://www.amosclaud.com/"
CANONICAL_HOST = "www.amosclaud.com"
FORBIDDEN_URLS = (
    "http://www.amosclaud.com",
    "https://amosclaud.com",
    "http://amosclaud.com",
)
AUTHORITATIVE_FILES = (
    ROOT / ".env.example",
    ROOT / ".circleci" / "config.yml",
    ROOT / "docker-compose.prod.yml",
    ROOT / "pyproject.toml",
    ROOT / "amoscloud_ai" / "config.py",
    ROOT / "amoscloud_ai" / "solo_shell.py",
    ROOT / "amosclaud_agent_sdk" / "client.py",
)


def test_authoritative_autonomous_domain_files_use_canonical_forms() -> None:
    violations: list[str] = []
    for path in AUTHORITATIVE_FILES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for forbidden in FORBIDDEN_URLS:
            if forbidden in text:
                violations.append(f"{path.relative_to(ROOT)} contains {forbidden}")

    assert not violations, "Legacy Amosclaud Autonomous domains found:\n" + "\n".join(violations)


def test_cname_uses_canonical_hostname() -> None:
    assert (ROOT / "CNAME").read_text(encoding="utf-8").strip() == CANONICAL_HOST


def test_domain_policy_declares_canonical_url() -> None:
    policy = (ROOT / "docs" / "DOMAIN_OWNERSHIP.md").read_text(encoding="utf-8")
    assert CANONICAL_URL in policy
    assert CANONICAL_HOST in policy
