#!/usr/bin/env python3
"""Create or update the canonical Amosclaud GitHub labels without deleting others."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

API_ROOT = "https://api.github.com"


def load_manifest(path: Path) -> list[dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Label manifest must contain a list")

    labels: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Label entry {index} must be a mapping")
        name = str(item.get("name") or "").strip()
        color = str(item.get("color") or "").strip().lstrip("#").lower()
        description = str(item.get("description") or "").strip()
        if not name:
            raise ValueError(f"Label entry {index} has no name")
        if name in seen:
            raise ValueError(f"Duplicate label name: {name}")
        if len(color) != 6 or any(character not in "0123456789abcdef" for character in color):
            raise ValueError(f"Label {name!r} has an invalid six-digit color")
        if len(description) > 100:
            raise ValueError(f"Label {name!r} description exceeds GitHub's 100-character limit")
        seen.add(name)
        labels.append({"name": name, "color": color, "description": description})
    return labels


def request_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Label-Sync/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode()
        return json.loads(body) if body else None


def list_labels(repository: str, token: str) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        url = f"{API_ROOT}/repos/{repository}/labels?per_page=100&page={page}"
        batch = request_json("GET", url, token)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected label response")
        for label in batch:
            labels[str(label["name"])] = label
        if len(batch) < 100:
            return labels
        page += 1


def synchronize(
    repository: str,
    token: str,
    desired: list[dict[str, str]],
    *,
    dry_run: bool,
) -> dict[str, list[str]]:
    existing = list_labels(repository, token)
    result: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": []}

    for label in desired:
        current = existing.get(label["name"])
        if current is None:
            result["created"].append(label["name"])
            if not dry_run:
                request_json(
                    "POST",
                    f"{API_ROOT}/repos/{repository}/labels",
                    token,
                    label,
                )
            continue

        current_color = str(current.get("color") or "").lower()
        current_description = str(current.get("description") or "")
        if current_color == label["color"] and current_description == label["description"]:
            result["unchanged"].append(label["name"])
            continue

        result["updated"].append(label["name"])
        if not dry_run:
            encoded_name = urllib.parse.quote(label["name"], safe="")
            request_json(
                "PATCH",
                f"{API_ROOT}/repos/{repository}/labels/{encoded_name}",
                token,
                {
                    "new_name": label["name"],
                    "color": label["color"],
                    "description": label["description"],
                },
            )

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=".github/labels.yml")
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    try:
        desired = load_manifest(Path(arguments.manifest))
        if arguments.dry_run and (not arguments.repository or not arguments.token):
            print(json.dumps({"validated": len(desired), "network": "skipped"}, indent=2))
            return 0
        if not arguments.repository or "/" not in arguments.repository:
            raise ValueError("Provide --repository owner/name or set GITHUB_REPOSITORY")
        if not arguments.token:
            raise ValueError("Provide --token or set GITHUB_TOKEN")
        result = synchronize(
            arguments.repository,
            arguments.token,
            desired,
            dry_run=arguments.dry_run,
        )
    except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
        print(f"label sync failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"repository": arguments.repository, "dry_run": arguments.dry_run, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
