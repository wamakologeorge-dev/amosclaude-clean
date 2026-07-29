"""Portable IDE client for the governed Amosclaud Copilot API.

The client is intentionally a thin adapter. It does not create another autonomous
runtime; every plan and execution request enters the existing Amosclaud Copilot
and Autonomous pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://www.amosclaud.com"
MAX_SELECTION_CHARS = 16_000
MAX_TASK_CHARS = 12_000
SENSITIVE_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


class IDEClientError(RuntimeError):
    """Raised when local validation or an Amosclaud request fails."""


def normalize_base_url(value: str | None) -> str:
    candidate = (value or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(candidate)
    secure_remote = parsed.scheme == "https" and bool(parsed.hostname)
    local_development = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if not (secure_remote or local_development):
        raise IDEClientError(
            "AMOSCLAUD_URL must use HTTPS, except for exact localhost development hosts"
        )
    return candidate


def validate_relative_path(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise IDEClientError("Editor file paths must be repository-relative and cannot contain '..'")
    return str(path)


def is_sensitive_path(value: str | None) -> bool:
    if not value:
        return False
    path = PurePosixPath(value.lower())
    name = path.name
    return (
        name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or path.suffix in SENSITIVE_SUFFIXES
        or any(part in {"secrets", ".secrets"} for part in path.parts)
    )


def bounded_selection(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:MAX_SELECTION_CHARS]


def build_context(
    *,
    repository: str | None = None,
    branch: str = "main",
    file_path: str | None = None,
    language: str | None = None,
    selection: str | None = None,
    source: str = "amosclaud-ide",
) -> dict[str, Any]:
    safe_path = validate_relative_path(file_path)
    if is_sensitive_path(safe_path):
        raise IDEClientError("Sensitive files cannot be sent as IDE context")
    context: dict[str, Any] = {
        "branch": branch.strip() or "main",
        "source": source,
    }
    optional = {
        "repository": repository.strip() if repository else None,
        "file_path": safe_path,
        "language": language.strip() if language else None,
        "selection": bounded_selection(selection),
    }
    context.update({key: value for key, value in optional.items() if value is not None})
    return context


def build_payload(
    task: str,
    *,
    requested_agent: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_task = task.strip()
    if not clean_task:
        raise IDEClientError("A task is required")
    if len(clean_task) > MAX_TASK_CHARS:
        raise IDEClientError(f"Tasks are limited to {MAX_TASK_CHARS} characters")
    payload: dict[str, Any] = {"task": clean_task, "context": context or {}}
    if requested_agent:
        payload["requested_agent"] = requested_agent.strip()
    return payload


def read_selection_file(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise IDEClientError(f"Selection file does not exist: {candidate}")
    if is_sensitive_path(candidate.as_posix()):
        raise IDEClientError("Sensitive files cannot be read as editor selections")
    with candidate.open("r", encoding="utf-8", errors="replace") as stream:
        return stream.read(MAX_SELECTION_CHARS)


@dataclass(frozen=True)
class ClientCredentials:
    bearer_token: str | None = None
    session_cookie: str | None = None

    @classmethod
    def from_environment(cls) -> "ClientCredentials":
        return cls(
            bearer_token=(
                os.getenv("AMOSCLAUD_AUTONOMOUS_KEY") or os.getenv("AMOSCLAUD_TOKEN") or None
            ),
            session_cookie=os.getenv("AMOSCLAUD_SESSION_COOKIE") or None,
        )


class AmosclaudIDEClient:
    """Small HTTP adapter for the canonical Amosclaud Copilot endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        credentials: ClientCredentials | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = normalize_base_url(base_url or os.getenv("AMOSCLAUD_URL"))
        self.credentials = credentials or ClientCredentials.from_environment()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "amosclaud-ide/1"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.credentials.bearer_token:
            headers["Authorization"] = f"Bearer {self.credentials.bearer_token}"
        elif self.credentials.session_cookie:
            headers["Cookie"] = f"amos_session={self.credentials.session_cookie}"
        elif authenticated:
            raise IDEClientError(
                "Set AMOSCLAUD_AUTONOMOUS_KEY, AMOSCLAUD_TOKEN, or AMOSCLAUD_SESSION_COOKIE"
            )

        request = Request(
            urljoin(f"{self.base_url}/", path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise IDEClientError(f"Amosclaud returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise IDEClientError(f"Could not reach Amosclaud: {exc.reason}") from exc
        try:
            result = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise IDEClientError("Amosclaud returned a non-JSON response") from exc
        if not isinstance(result, dict):
            raise IDEClientError("Amosclaud returned an unexpected response shape")
        return result

    def doctor(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/copilot")

    def agents(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/copilot/agents")

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/copilot/plan", payload, authenticated=True)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/copilot/run", payload, authenticated=True)


def _context_from_args(args: argparse.Namespace, source: str) -> dict[str, Any]:
    return build_context(
        repository=args.repository,
        branch=args.branch,
        file_path=args.file,
        language=args.language,
        selection=read_selection_file(args.selection_file),
        source=source,
    )


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _add_task_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task", nargs="?", help="Developer request for Amosclaud")
    parser.add_argument("--agent", dest="requested_agent")
    parser.add_argument("--repository")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--file", help="Repository-relative active file path")
    parser.add_argument("--language")
    parser.add_argument("--selection-file", help="Temporary UTF-8 file containing selected text")


def _interactive_chat(client: AmosclaudIDEClient, args: argparse.Namespace) -> int:
    agent = args.requested_agent
    execute = bool(args.execute)
    print("Amosclaud Autonomous IDE chat. Commands: /agent NAME, /plan, /run, /quit")
    while True:
        try:
            message = input("amosclaud> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not message:
            continue
        if message in {"/quit", "/exit"}:
            return 0
        if message.startswith("/agent "):
            agent = message.split(maxsplit=1)[1].strip() or None
            print(f"Internal capability preference: {agent or 'automatic'}")
            continue
        if message == "/plan":
            execute = False
            print("Chat mode: plan only")
            continue
        if message == "/run":
            execute = True
            print("Chat mode: authorized execution")
            continue
        context = build_context(
            repository=args.repository,
            branch=args.branch,
            source="amosclaud-ide-chat",
        )
        payload = build_payload(message, requested_agent=agent, context=context)
        result = client.run(payload) if execute else client.plan(payload)
        _print_json(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amosclaud-ide",
        description="Use Amosclaud Autonomous from VS Code, Xcode, terminals, and local editors.",
    )
    parser.add_argument("--url", help="Amosclaud base URL; defaults to AMOSCLAUD_URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check the public Copilot profile")
    subparsers.add_parser("agents", help="List internal capability roles")

    plan = subparsers.add_parser("plan", help="Preview routing without starting execution")
    _add_task_arguments(plan)

    run = subparsers.add_parser("run", help="Authorize the governed Autonomous workflow")
    _add_task_arguments(run)

    chat = subparsers.add_parser("chat", help="Open an interactive IDE chat")
    chat.add_argument("--agent", dest="requested_agent")
    chat.add_argument("--repository")
    chat.add_argument("--branch", default="main")
    chat.add_argument("--execute", action="store_true", help="Start in authorized execution mode")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    client = AmosclaudIDEClient(base_url=args.url)
    try:
        if args.command == "doctor":
            _print_json(client.doctor())
            return 0
        if args.command == "agents":
            _print_json(client.agents())
            return 0
        if args.command == "chat":
            return _interactive_chat(client, args)
        task = args.task or input("Task: ").strip()
        context = _context_from_args(args, f"amosclaud-ide-{args.command}")
        payload = build_payload(task, requested_agent=args.requested_agent, context=context)
        result = client.plan(payload) if args.command == "plan" else client.run(payload)
        _print_json(result)
        return 0
    except IDEClientError as exc:
        print(f"amosclaud-ide: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
