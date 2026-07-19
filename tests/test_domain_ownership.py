from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_URL = "http://www.amosclaud.com/"
CANONICAL_HOST = "www.amosclaud.com"
FORBIDDEN_URLS = (
    "https://amosclaud.com",
    "https://www.amosclaud.com",
    "http://amosclaud.com",
)
EXCLUDED_PATHS = {
    "docs/DOMAIN_OWNERSHIP.md",  # documents the separation intentionally
    "tests/test_domain_ownership.py",  # contains the forbidden fixtures
}
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def is_text_candidate(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    if relative in EXCLUDED_PATHS:
        return False
    return path.name in {"CNAME", "Caddyfile"} or path.suffix.lower() in TEXT_SUFFIXES


def test_autonomous_domain_uses_only_canonical_forms() -> None:
    violations: list[str] = []
    for path in tracked_files():
        if not path.is_file() or not is_text_candidate(path):
            continue
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
