"""Repository behavior automation for labels and safe maintenance.

This module intentionally uses only the Python standard library so GitHub
administration jobs do not install or execute project dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

LABELS: dict[str, tuple[str, str]] = {
    "area:backend": ("1d76db", "Python services, APIs, domain logic, or persistence"),
    "area:frontend": ("a2eeef", "Web, static assets, or user-interface changes"),
    "area:ci": ("5319e7", "GitHub Actions, automation, or repository policy"),
    "area:docs": ("0075ca", "Documentation-only or documentation-focused work"),
    "area:tests": ("bfd4f2", "Test coverage, fixtures, or verification"),
    "area:deployment": ("f9d0c4", "Docker, infrastructure, release, or deployment"),
    "type:bug": ("d73a4a", "A defect, failure, regression, or repair"),
    "type:feature": ("0e8a16", "A new capability or enhancement"),
    "type:dependencies": ("0366d6", "Dependency or lock-file maintenance"),
    "size:xs": ("c5def5", "Very small pull request"),
    "size:s": ("bfe5bf", "Small pull request"),
    "size:m": ("fbca04", "Medium pull request"),
    "size:l": ("f9a825", "Large pull request"),
    "status:needs-triage": ("d4c5f9", "Needs maintainer classification"),
    "status:stale": ("ededed", "No activity within the configured maintenance window"),
    "status:keep-open": ("ffffff", "Exempt from scheduled stale labeling"),
    "autofix": ("7057ff", "Maintainer-approved automatic formatting"),
    "security-sensitive": ("b60205", "Touches authentication, secrets, or security controls"),
}

CLASSIFICATION_PREFIXES = ("area:", "type:", "size:")
CLASSIFICATION_EXACT = {"status:needs-triage"}
STALE_EXEMPT = {"status:keep-open", "security-sensitive"}

BACKEND_PREFIXES = (
    "amoscloud_ai/",
    "amosclaud_os/",
    "amosclaud_agent_sdk/",
    "amosclaud_language/",
    "amosclaud_model/",
    "amosclaud_metrics/",
    "amosclaud_mcp/",
    "Amosclaud/",
)
FRONTEND_PREFIXES = ("web/", "pages-site/", "static/", "templates/")
DEPLOYMENT_PREFIXES = (
    "docker/",
    "Infrastructure/",
    "deployment/",
    "deployments/",
    "railway",
)
SECURITY_FRAGMENTS = (
    "auth",
    "security",
    "secret",
    "service_key",
    "passkey",
    "credential",
    ".github/workflows/",
)


def _text(*parts: str | None) -> str:
    return " ".join(part or "" for part in parts).lower()


def _has_any(value: str, needles: Iterable[str]) -> bool:
    return any(needle in value for needle in needles)


def classify_issue(title: str, body: str | None = None) -> set[str]:
    """Return bounded labels derived from issue text."""
    text = _text(title, body)
    labels: set[str] = set()

    if _has_any(text, ("bug", "error", "failure", "failed", "broken", "regression", "fix")):
        labels.add("type:bug")
    elif _has_any(text, ("feature", "enhancement", "request", "proposal", "support for")):
        labels.add("type:feature")

    if _has_any(text, ("documentation", "docs", "readme")):
        labels.add("area:docs")
    if _has_any(text, ("deploy", "deployment", "railway", "docker", "release", "production")):
        labels.add("area:deployment")
    if _has_any(text, ("security", "vulnerability", "secret", "credential", "token leak")):
        labels.add("security-sensitive")

    if not labels:
        labels.add("status:needs-triage")
    return labels


def classify_pull_request(
    files: Iterable[str],
    *,
    title: str = "",
    body: str | None = None,
    author: str = "",
) -> set[str]:
    """Return path-, size-, and intent-based labels for a pull request."""
    paths = [path.strip() for path in files if path.strip()]
    labels: set[str] = set()
    text = _text(title, body)

    if any(path.startswith(BACKEND_PREFIXES) or path.endswith(".py") for path in paths):
        labels.add("area:backend")
    if any(path.startswith(FRONTEND_PREFIXES) for path in paths):
        labels.add("area:frontend")
    if any(path.startswith(".github/") for path in paths):
        labels.add("area:ci")
    if any(path.startswith("tests/") or "/tests/" in path for path in paths):
        labels.add("area:tests")
    if any(
        path.startswith(DEPLOYMENT_PREFIXES)
        or path.startswith("Dockerfile")
        or "docker-compose" in path
        for path in paths
    ):
        labels.add("area:deployment")
    if paths and all(
        path.startswith(("docs/", ".github/ISSUE_TEMPLATE/", ".github/PULL_REQUEST_TEMPLATE"))
        or path.lower().endswith((".md", ".rst", ".txt"))
        for path in paths
    ):
        labels.add("area:docs")

    dependency_files = {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
    }
    if author.lower().startswith("dependabot") or any(
        path.rsplit("/", 1)[-1] in dependency_files for path in paths
    ):
        labels.add("type:dependencies")
    elif _has_any(text, ("fix", "bug", "repair", "regression")):
        labels.add("type:bug")
    elif _has_any(text, ("add", "feature", "implement", "support", "create")):
        labels.add("type:feature")

    if any(_has_any(path.lower(), SECURITY_FRAGMENTS) for path in paths) or _has_any(
        text, ("security", "credential", "secret", "authentication", "authorization")
    ):
        labels.add("security-sensitive")

    count = len(paths)
    if count <= 5:
        labels.add("size:xs")
    elif count <= 15:
        labels.add("size:s")
    elif count <= 40:
        labels.add("size:m")
    else:
        labels.add("size:l")

    if not any(label.startswith(("area:", "type:")) for label in labels):
        labels.add("status:needs-triage")
    return labels


class GitHubClient:
    """Small GitHub REST client with explicit repository-scoped operations."""

    def __init__(self, repository: str, token: str) -> None:
        if "/" not in repository:
            raise ValueError("repository must use owner/name format")
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.repository = repository
        self.token = token
        self.base_url = f"https://api.github.com/repos/{repository}"

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "amosclaud-repository-behavior",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                if response.status not in expected:
                    raise RuntimeError(
                        f"GitHub returned HTTP {response.status} for {method} {path}"
                    )
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API failed: {method} {path}: HTTP {exc.code}: {detail}"
            ) from exc

    def paginate(self, path: str, *, limit_pages: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, limit_pages + 1):
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise RuntimeError(f"Expected a list from {path}")
            items.extend(batch)
            if len(batch) < 100:
                break
        return items


def ensure_labels(client: GitHubClient) -> None:
    existing = {item["name"] for item in client.paginate("/labels")}
    for name, (color, description) in LABELS.items():
        if name in existing:
            continue
        client.request(
            "POST",
            "/labels",
            {"name": name, "color": color, "description": description},
            expected=(201,),
        )


def _current_labels(client: GitHubClient, number: int) -> set[str]:
    item = client.request("GET", f"/issues/{number}")
    return {entry["name"] for entry in item.get("labels", [])}


def apply_classification(client: GitHubClient, number: int, desired: set[str]) -> None:
    """Replace only automation-owned classification labels."""
    current = _current_labels(client, number)
    removable = {
        label
        for label in current
        if label.startswith(CLASSIFICATION_PREFIXES) or label in CLASSIFICATION_EXACT
    }
    for label in sorted(removable - desired):
        client.request(
            "DELETE",
            f"/issues/{number}/labels/{quote(label, safe='')}",
            expected=(200,),
        )

    additions = sorted(desired - current)
    if additions:
        client.request("POST", f"/issues/{number}/labels", {"labels": additions})

    if "status:stale" in current:
        client.request(
            "DELETE",
            f"/issues/{number}/labels/{quote('status:stale', safe='')}",
            expected=(200,),
        )


def label_issue(client: GitHubClient, number: int) -> set[str]:
    issue = client.request("GET", f"/issues/{number}")
    desired = classify_issue(issue.get("title", ""), issue.get("body"))
    apply_classification(client, number, desired)
    return desired


def label_pull_request(client: GitHubClient, number: int) -> set[str]:
    pull = client.request("GET", f"/pulls/{number}")
    files = [item["filename"] for item in client.paginate(f"/pulls/{number}/files")]
    desired = classify_pull_request(
        files,
        title=pull.get("title", ""),
        body=pull.get("body"),
        author=(pull.get("user") or {}).get("login", ""),
    )
    apply_classification(client, number, desired)
    return desired


def refresh_item(client: GitHubClient, number: int) -> bool:
    """Remove the stale marker when a person adds new activity."""
    current = _current_labels(client, number)
    if "status:stale" not in current:
        return False
    client.request(
        "DELETE",
        f"/issues/{number}/labels/{quote('status:stale', safe='')}",
        expected=(200,),
    )
    return True


def run_maintenance(client: GitHubClient, *, stale_days: int) -> dict[str, int]:
    """Label inactive work without closing, merging, deleting, or rewriting anything."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(7, stale_days))
    marked = 0

    for item in client.paginate("/issues?state=open&sort=updated&direction=asc", limit_pages=5):
        number = int(item["number"])
        labels = {entry["name"] for entry in item.get("labels", [])}
        updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))

        if labels & STALE_EXEMPT:
            continue
        if updated < cutoff and "status:stale" not in labels:
            client.request("POST", f"/issues/{number}/labels", {"labels": ["status:stale"]})
            client.request(
                "POST",
                f"/issues/{number}/comments",
                {
                    "body": (
                        f"This item has had no activity for at least {max(7, stale_days)} days. "
                        "It was labeled `status:stale` for review, but it was not closed. "
                        "Any new activity removes the stale label."
                    )
                },
                expected=(201,),
            )
            marked += 1

    return {"marked_stale": marked}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/name form",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN", ""),
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue_parser = subparsers.add_parser("label-issue")
    issue_parser.add_argument("--number", type=int, required=True)

    pull_parser = subparsers.add_parser("label-pr")
    pull_parser.add_argument("--number", type=int, required=True)

    maintenance_parser = subparsers.add_parser("maintenance")
    maintenance_parser.add_argument("--stale-days", type=int, default=30)

    refresh_parser = subparsers.add_parser("refresh")
    refresh_parser.add_argument("--number", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = GitHubClient(args.repository, args.token)
    ensure_labels(client)

    if args.command == "label-issue":
        result: Any = sorted(label_issue(client, args.number))
    elif args.command == "label-pr":
        result = sorted(label_pull_request(client, args.number))
    elif args.command == "refresh":
        result = {"refreshed": refresh_item(client, args.number)}
    else:
        result = run_maintenance(client, stale_days=args.stale_days)

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
