from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOT_NAMES = ("@amosclaud", "@amosclaud-bot")
COMMANDS = {"help", "status", "inspect", "verify", "review", "fix"}


@dataclass(frozen=True)
class BotResponse:
    body: str
    should_comment: bool = True


def parse_command(text: str) -> tuple[str | None, str]:
    normalized = " ".join((text or "").strip().split())
    lowered = normalized.lower()
    matched_name = next((name for name in BOT_NAMES if lowered.startswith(name)), None)
    if not matched_name:
        return None, ""
    remainder = normalized[len(matched_name) :].strip()
    if not remainder:
        return "help", ""
    command, _, objective = remainder.partition(" ")
    command = command.lower().strip()
    return (command if command in COMMANDS else "help"), objective.strip()


class AmosclaudBot:
    """Small GitHub-native control plane for the existing Amosclaud runtime."""

    def __init__(self, repository: str, token: str = "") -> None:
        self.repository = repository
        self.token = token
        self.api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.api}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "amosclaud-bot",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed ({exc.code}): {detail[:500]}") from exc

    def post_comment(self, issue_number: int, body: str) -> None:
        self._request(
            "POST",
            f"/repos/{self.repository}/issues/{issue_number}/comments",
            {"body": body},
        )

    def _autonomous_request(self, objective: str) -> str:
        endpoint = os.getenv("AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT", "").strip()
        api_key = os.getenv("AMOSCLAUD_API_KEY", "").strip()
        if not endpoint:
            return (
                "The GitHub bot is active, but autonomous write execution is not connected yet. "
                "Set `AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT` to the existing Amosclaud Autonomous endpoint "
                "and provide `AMOSCLAUD_API_KEY` as a GitHub Actions secret."
            )
        payload = json.dumps({"objective": objective, "mode": "autonomous-check"}).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "amosclaud-bot"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001 - surfaced safely to the GitHub conversation
            return f"Amosclaud Autonomous could not be reached: `{type(exc).__name__}`."
        summary = str(data.get("summary") or data.get("detail") or data.get("status") or "Request completed.")
        return summary[:3000]

    def handle_comment(self, payload: dict[str, Any]) -> BotResponse:
        comment = payload.get("comment") or {}
        command, objective = parse_command(str(comment.get("body") or ""))
        if not command:
            return BotResponse("", should_comment=False)

        issue = payload.get("issue") or {}
        number = issue.get("number", "unknown")
        is_pr = bool(issue.get("pull_request"))
        target = f"pull request #{number}" if is_pr else f"issue #{number}"

        if command == "help":
            return BotResponse(
                "### Amosclaud Bot\n"
                "I am active in this repository. Commands:\n\n"
                "- `@amosclaud status` — confirm bot/runtime wiring\n"
                "- `@amosclaud inspect <objective>` — inspect through Amosclaud Autonomous when connected\n"
                "- `@amosclaud verify <objective>` — request verification\n"
                "- `@amosclaud review <objective>` — request a repository review\n"
                "- `@amosclaud fix <objective>` — request an autonomous fix\n"
            )

        if command == "status":
            connected = bool(os.getenv("AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT", "").strip())
            return BotResponse(
                "### Amosclaud Bot status\n"
                f"- GitHub event handling: **ready**\n"
                f"- Repository: `{self.repository}`\n"
                f"- Target: {target}\n"
                f"- Autonomous endpoint: **{'connected' if connected else 'not configured'}**"
            )

        request_objective = objective or f"{command.capitalize()} {target}"
        summary = self._autonomous_request(request_objective)
        return BotResponse(
            f"### Amosclaud Bot — {command}\n"
            f"**Objective:** {request_objective}\n\n"
            f"{summary}"
        )

    def handle_workflow_run(self, payload: dict[str, Any]) -> tuple[int | None, BotResponse]:
        run = payload.get("workflow_run") or {}
        if run.get("action") == "requested" or run.get("conclusion") != "failure":
            return None, BotResponse("", should_comment=False)
        prs = run.get("pull_requests") or []
        if not prs:
            return None, BotResponse("", should_comment=False)
        number = prs[0].get("number")
        if not isinstance(number, int):
            return None, BotResponse("", should_comment=False)
        name = run.get("name") or "GitHub Actions"
        url = run.get("html_url") or ""
        body = (
            "### Amosclaud Bot detected a CI failure\n"
            f"Workflow **{name}** failed for this pull request.\n\n"
            f"Run: {url}\n\n"
            "Comment `@amosclaud inspect CI failure` to inspect it, or "
            "`@amosclaud fix CI failure` when the Autonomous endpoint is connected."
        )
        return number, BotResponse(body)


def run_from_environment() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not event_path or not repository:
        raise RuntimeError("GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token)

    if event_name == "issue_comment":
        number = int((payload.get("issue") or {}).get("number"))
        response = bot.handle_comment(payload)
        if response.should_comment:
            bot.post_comment(number, response.body)
        return 0

    if event_name == "workflow_run":
        number, response = bot.handle_workflow_run(payload)
        if number is not None and response.should_comment:
            bot.post_comment(number, response.body)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(run_from_environment())
