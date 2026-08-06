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
    assert payload["completion_comment"] == ".Amosclaud/main clean_100%"
    assert payload["canonical_runtime"] == "amoscloud_ai.main:app"
    assert "platform_runtime" in payload["subsystems_checked"]
    assert "model_context_protocol" in payload["subsystems_checked"]
    assert "github_automation" in payload["subsystems_checked"]
