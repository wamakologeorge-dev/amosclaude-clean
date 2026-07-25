"""Register a model station with Amosclaud and print its environment.

    python -m station.register --name "Studio station" --model qwen2.5-coder:1.5b

Authentication uses your normal Amosclaud browser session. Either pass the
``amos_session`` cookie value with ``--session`` (or the ``AMOSCLAUD_SESSION``
environment variable), or pass ``--email`` and let the tool sign in for you.

The station credential is printed exactly once: Amosclaud stores only its hash
and cannot show it again.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

from station import USER_AGENT
from station.config import (
    DEFAULT_BACKEND,
    DEFAULT_MODEL,
    DEFAULT_URL,
    INFERENCE_CAPABILITY,
    default_station_name,
)
from station.transport import HttpError, TransportError, request_json


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def login(base_url: str, email: str, password: str, timeout: float = 30.0) -> str:
    """Sign in and return the ``amos_session`` cookie value."""
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/v1/auth/login", data=body, method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            cookies = response.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as error:
        raise HttpError(error.code, "sign in failed") from None
    except urllib.error.URLError as error:
        raise TransportError(str(error.reason)) from None
    for cookie in cookies:
        if cookie.startswith("amos_session="):
            return cookie.split("=", 1)[1].split(";", 1)[0]
    raise RuntimeError("Amosclaud did not return a session cookie")


def register_station(
    base_url: str,
    session: str,
    name: str,
    capabilities: list[str],
    labels: list[str],
    timeout: float = 30.0,
) -> dict:
    payload = request_json(
        f"{base_url}/api/v1/server-stations",
        method="POST",
        payload={"name": name, "capabilities": capabilities, "labels": labels},
        headers={"Cookie": f"amos_session={session}"},
        timeout=timeout,
    )
    if not isinstance(payload, dict) or not payload.get("station_token"):
        raise RuntimeError("Amosclaud did not return a station credential")
    return payload


def environment_block(
    base_url: str, station_id: str, token: str, backend: str, model: str
) -> str:
    lines = [
        f"AMOSCLAUD_URL={base_url}",
        f"AMOSCLAUD_STATION_ID={station_id}",
        f"AMOSCLAUD_STATION_TOKEN={token}",
        f"AMOSCLAUD_STATION_BACKEND={backend}",
        f"AMOSCLAUD_STATION_MODEL={model}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m station.register",
        description="Register an Amosclaud model station and print its environment.",
    )
    parser.add_argument("--url", default=os.getenv("AMOSCLAUD_URL", DEFAULT_URL))
    parser.add_argument("--name", default=os.getenv("AMOSCLAUD_STATION_NAME", ""))
    parser.add_argument("--session", default=os.getenv("AMOSCLAUD_SESSION", ""))
    parser.add_argument("--email", default=os.getenv("AMOSCLAUD_EMAIL", ""))
    parser.add_argument(
        "--password",
        default=os.getenv("AMOSCLAUD_PASSWORD", ""),
        help="Omit to be prompted securely.",
    )
    parser.add_argument(
        "--backend", default=os.getenv("AMOSCLAUD_STATION_BACKEND", DEFAULT_BACKEND)
    )
    parser.add_argument(
        "--model", default=os.getenv("AMOSCLAUD_STATION_MODEL", DEFAULT_MODEL)
    )
    parser.add_argument("--capabilities", default=INFERENCE_CAPABILITY)
    parser.add_argument("--labels", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = args.url.rstrip("/")
    name = (args.name or default_station_name()).strip()
    capabilities = _split(args.capabilities) or [INFERENCE_CAPABILITY]
    if INFERENCE_CAPABILITY not in capabilities:
        capabilities.insert(0, INFERENCE_CAPABILITY)

    session = args.session.strip()
    try:
        if not session:
            if not args.email:
                print(
                    "Provide --session with your amos_session cookie, or --email to sign in.",
                    file=sys.stderr,
                )
                return 2
            password = args.password or getpass.getpass("Amosclaud password: ")
            session = login(base_url, args.email, password, timeout=args.timeout)
        created = register_station(
            base_url, session, name, capabilities, _split(args.labels), timeout=args.timeout
        )
    except (HttpError, TransportError, RuntimeError) as error:
        print(f"Registration failed: {error}", file=sys.stderr)
        return 1

    print(f"Registered station {created['id']} ({created.get('name', name)}).")
    print("Copy the credential below now. Amosclaud stores only its hash.\n")
    print(
        environment_block(
            base_url, created["id"], created["station_token"], args.backend, args.model
        )
    )
    print("\nStart the agent with:  python -m station")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
