#!/usr/bin/env python3
"""Fail a pull request when GitHub code scanning reports any open alert.

The gate is intentionally severity-independent: every open code-scanning alert
associated with the pull request is treated as a blocking security threat until
it is fixed or explicitly dismissed through GitHub's audited security workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_API_VERSION = "2022-11-28"
_PAGE_SIZE = 100
_MAX_PAGES = 100
UrlOpen = Callable[..., Any]


@dataclass(frozen=True)
class GateResult:
    status: str
    repository: str
    pull_request: int
    threats: tuple[dict[str, object], ...]
    detail: str

    @property
    def exit_code(self) -> int:
        if self.status == "PASSED":
            return 0
        if self.status == "THREATS_DETECTED":
            return 1
        return 2

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "amosclaud.advanced-security-gate.v1",
            "status": self.status,
            "repository": self.repository,
            "pull_request": self.pull_request,
            "threat_count": len(self.threats),
            "threats": list(self.threats),
            "detail": self.detail,
            "exit_code": self.exit_code,
        }


def _request_json(
    url: str,
    token: str,
    *,
    urlopen: UrlOpen,
) -> tuple[int, object]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "amosclaud-advanced-security-gate",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return int(getattr(response, "status", 200)), json.loads(raw or "[]")
    except urllib.error.HTTPError as exc:
        return int(exc.code), {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
        return 0, {}


def _threat(alert: Mapping[str, object]) -> dict[str, object]:
    rule = alert.get("rule") if isinstance(alert.get("rule"), Mapping) else {}
    instance = (
        alert.get("most_recent_instance")
        if isinstance(alert.get("most_recent_instance"), Mapping)
        else {}
    )
    location = instance.get("location") if isinstance(instance.get("location"), Mapping) else {}
    return {
        "number": alert.get("number"),
        "severity": rule.get("security_severity_level") or rule.get("severity") or "unknown",
        "rule": rule.get("id") or rule.get("name") or "unknown",
        "description": rule.get("description") or "Code scanning threat",
        "path": location.get("path") or "unknown",
        "start_line": location.get("start_line"),
        "url": alert.get("html_url") or "",
    }


def evaluate_pull_request(
    *,
    repository: str,
    pull_request: int,
    token: str,
    api_url: str = "https://api.github.com",
    urlopen: UrlOpen = urllib.request.urlopen,
) -> GateResult:
    if not repository or "/" not in repository:
        return GateResult("BLOCKED", repository, pull_request, (), "repository is invalid")
    if pull_request <= 0:
        return GateResult("BLOCKED", repository, pull_request, (), "pull request is invalid")
    if not token:
        return GateResult("BLOCKED", repository, pull_request, (), "GitHub token is missing")

    alerts: list[Mapping[str, object]] = []
    api = api_url.rstrip("/")
    for page in range(1, _MAX_PAGES + 1):
        query = urllib.parse.urlencode(
            {
                "pr": pull_request,
                "state": "open",
                "per_page": _PAGE_SIZE,
                "page": page,
            }
        )
        status, payload = _request_json(
            f"{api}/repos/{repository}/code-scanning/alerts?{query}",
            token,
            urlopen=urlopen,
        )
        if status != 200:
            detail = {
                403: "GitHub Code Security is unavailable or the token lacks code-scanning read access",
                404: "the repository or code-scanning endpoint was not found",
                503: "GitHub code scanning is temporarily unavailable",
            }.get(status, f"code-scanning API request failed with status {status or 'network-error'}")
            return GateResult("BLOCKED", repository, pull_request, (), detail)
        if not isinstance(payload, list):
            return GateResult(
                "BLOCKED",
                repository,
                pull_request,
                (),
                "code-scanning API returned an invalid payload",
            )
        batch = [item for item in payload if isinstance(item, Mapping)]
        alerts.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break

    threats = tuple(_threat(alert) for alert in alerts)
    if threats:
        return GateResult(
            "THREATS_DETECTED",
            repository,
            pull_request,
            threats,
            "every open pull-request code-scanning alert is blocking",
        )
    return GateResult(
        "PASSED",
        repository,
        pull_request,
        (),
        "no open code-scanning alerts were reported for the pull request",
    )


def render_markdown(result: GateResult) -> str:
    marker = {
        "PASSED": "🟩",
        "THREATS_DETECTED": "🟥",
        "BLOCKED": "🟥",
    }.get(result.status, "⬜")
    lines = [
        "### Amosclaud Advanced Security Threat Gate",
        "",
        f"**Result:** {marker} {result.status}",
        f"**Pull request:** #{result.pull_request}",
        f"**Threats:** {len(result.threats)}",
        f"**Detail:** {result.detail}",
    ]
    for threat in result.threats[:20]:
        location = str(threat.get("path") or "unknown")
        if threat.get("start_line"):
            location += f":{threat['start_line']}"
        lines.append(
            f"- `{threat.get('severity')}` `{threat.get('rule')}` at `{location}` — "
            f"{threat.get('description')}"
        )
    if len(result.threats) > 20:
        lines.append(f"- ...and {len(result.threats) - 20} more threat(s)")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--pull-request",
        type=int,
        default=int(os.getenv("PR_NUMBER", "0") or "0"),
    )
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="markdown_path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_pull_request(
        repository=args.repository,
        pull_request=args.pull_request,
        token=os.getenv("GITHUB_TOKEN", ""),
        api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
    )
    payload = json.dumps(result.as_dict(), indent=2, sort_keys=True)
    report = render_markdown(result)
    print(payload)
    print(report)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as output:
            output.write(payload + "\n")
    if args.markdown_path:
        with open(args.markdown_path, "w", encoding="utf-8") as output:
            output.write(report)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
