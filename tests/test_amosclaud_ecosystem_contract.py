from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_amosclaud_main_ecosystem_contract(tmp_path: Path) -> None:
    report = tmp_path / "ecosystem-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci/verify_amosclaud_ecosystem.py",
            "--manifest",
            ".Amosclaud/main/ecosystem.json",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["status"] == "clean"
    assert payload["errors"] == []
    assert payload["completion_comment"] == ".Amosclaud/main clean_100%"
    assert payload["canonical_runtime"] == "amoscloud_ai.main:app"

    assert {
        "platform_runtime",
        "api_gateway",
        "database_layer",
        "control_plane",
        "model_context_protocol",
        "github_automation",
        "api_key_service",
        "developer_clients",
        "developer_web",
        "preview_service",
        "metrics",
        "platform_package",
        "operating_layer",
        "verification",
        "delivery",
        "documentation",
    }.issubset(payload["subsystems_checked"])

    assert set(payload["external_services_checked"]) == {
        "github",
        "railway",
        "redis",
        "mysql",
    }
    assert payload["external_service_statuses"] == {
        "github": "configured",
        "mysql": "provisioned",
        "railway": "active",
        "redis": "provisioned",
    }
    assert payload["environment_contract"]["github"] == [
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GITHUB_TOKEN_ENCRYPTION_KEY",
    ]
    assert payload["environment_contract"]["railway"] == [
        "AMOSCLAUD_PUBLIC_URL",
        "AUTH_DB_PATH",
        "REPOSITORY_STORAGE_PATH",
    ]
    assert payload["environment_contract"]["redis"] == ["REDIS_URL"]
    assert payload["environment_contract"]["mysql"] == ["MYSQL_URL"]

    assert payload["connections_checked"] == 20
    assert payload["connection_statuses"] == {
        "active": 10,
        "configured": 7,
        "planned": 3,
        "provisioned": 0,
    }
    assert any("planned" in warning for warning in payload["warnings"])
