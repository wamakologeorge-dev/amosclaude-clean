from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request

from amosclaud_agent_sdk.client import AmosclaudAgentClient
from amoscloud_ai.solo_shell import normalize_url
from sitecustomize import normalize_public_amosclaud_url, normalize_public_environment

ROOT = Path(__file__).resolve().parents[1]


def test_public_amosclaud_http_is_upgraded_to_canonical_https() -> None:
    assert (
        normalize_public_amosclaud_url("http://www.amosclaud.com/") == "https://www.amosclaud.com"
    )
    assert (
        normalize_public_amosclaud_url("http://amosclaud.com/api/v1/provider")
        == "https://www.amosclaud.com/api/v1/provider"
    )
    assert (
        normalize_public_amosclaud_url("http://www.amosclaud.com:80/v1/chat/completions")
        == "https://www.amosclaud.com/v1/chat/completions"
    )
    assert normalize_url("http://amosclaud.com:80") == "https://www.amosclaud.com"


def test_private_and_local_http_endpoints_are_preserved() -> None:
    assert normalize_public_amosclaud_url("http://127.0.0.1:8091") == "http://127.0.0.1:8091"
    assert (
        normalize_public_amosclaud_url("http://model-station:8000") == "http://model-station:8000"
    )
    assert normalize_url("http://localhost:8000") == "http://localhost:8000"


def test_environment_guard_upgrades_public_urls(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_API_URL", "http://www.amosclaud.com/")
    monkeypatch.setenv("AMOSCLAUD_PROVIDER_API_URL", "http://amosclaud.com:80")
    monkeypatch.setenv(
        "AMOSCLAUD_ALLOWED_ORIGINS",
        "http://www.amosclaud.com:80,http://localhost:8000",
    )

    normalize_public_environment()

    assert os.environ["AMOSCLAUD_API_URL"] == "https://www.amosclaud.com"
    assert os.environ["AMOSCLAUD_PROVIDER_API_URL"] == "https://www.amosclaud.com"
    assert os.environ["AMOSCLAUD_ALLOWED_ORIGINS"] == (
        "https://www.amosclaud.com,http://localhost:8000"
    )


def _run_environment_probe(
    *, cwd: Path, pythonpath: str | None = None, variable: str = "AMOSCLAUD_API_URL"
) -> str:
    env = dict(os.environ)
    env["AMOSCLAUD_API_URL"] = "http://www.amosclaud.com/"
    if variable == "AMOSCLAUD_ALLOWED_ORIGINS":
        env.pop(variable, None)
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sitecustomize, os; print(os.environ['{variable}'])",
        ],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def test_packaged_endpoint_guard_can_be_loaded_explicitly() -> None:
    assert _run_environment_probe(cwd=ROOT) == "https://www.amosclaud.com"


def test_repair_script_guard_loads_repository_policy() -> None:
    assert (
        _run_environment_probe(
            cwd=ROOT.parent,
            pythonpath=str(ROOT / ".github" / "scripts"),
        )
        == "https://www.amosclaud.com"
    )


def test_api_gateway_guard_sets_https_cors_default() -> None:
    assert (
        _run_environment_probe(
            cwd=ROOT.parent,
            pythonpath=str(ROOT / "api-gateway"),
            variable="AMOSCLAUD_ALLOWED_ORIGINS",
        )
        == "https://www.amosclaud.com,http://localhost:8000,http://127.0.0.1:8000"
    )


def test_sdk_upgrades_legacy_public_url_without_changing_request_method() -> None:
    client = AmosclaudAgentClient(base_url="http://amosclaud.com:80/")
    assert client.base_url == "https://www.amosclaud.com"

    request = Request(
        client.base_url + "/v1/chat/completions",
        data=b"{}",
        method="POST",
    )
    assert request.get_method() == "POST"
    assert urlsplit(request.full_url).scheme == "https"
