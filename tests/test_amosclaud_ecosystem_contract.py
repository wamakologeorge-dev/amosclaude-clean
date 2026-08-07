from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "ci" / "verify_amosclaud_ecosystem.py"


def run_verifier(root: Path, manifest: str, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--manifest",
            manifest,
            "--report",
            str(report),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_amosclaud_main_ecosystem_contract(tmp_path: Path) -> None:
    report = tmp_path / "ecosystem-report.json"
    result = run_verifier(ROOT, ".Amosclaud/main/ecosystem.json", report)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "clean"
    assert payload["completion_comment"] == ".Amosclaud/main clean_100%"
    assert payload["canonical_runtime"] == "amoscloud_ai.main:app"
    assert "platform_runtime" in payload["subsystems_checked"]
    assert "model_context_protocol" in payload["subsystems_checked"]
    assert "github_automation" in payload["subsystems_checked"]


def test_ecosystem_ignores_untracked_cache_but_rejects_tracked_archive(
    tmp_path: Path,
) -> None:
    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "runtime.py").write_text("app = object()\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Test ecosystem\n", encoding="utf-8")
    manifest = {
        "root": ".Amosclaud/main",
        "completion_comment": ".Amosclaud/main clean_100%",
        "canonical_runtime": "runtime:app",
        "canonical_cli_package": "package",
        "required_paths": ["README.md", "runtime.py", "package"],
        "subsystems": {
            "runtime": {
                "path": "runtime.py",
                "purpose": "Test runtime",
            }
        },
        "forbidden_root_files": [],
        "forbidden_root_globs": ["*.zip"],
        "forbidden_root_directories": ["__pycache__"],
    }
    (tmp_path / "ecosystem.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "add",
            "README.md",
            "runtime.py",
            "package/__init__.py",
            "ecosystem.json",
        ],
        cwd=tmp_path,
        check=True,
    )

    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "runtime.cpython.pyc").write_bytes(b"temporary cache")
    clean_report = tmp_path / "clean-report.json"
    clean = run_verifier(tmp_path, "ecosystem.json", clean_report)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean_report.read_text(encoding="utf-8"))["status"] == "clean"

    (tmp_path / "bundle.zip").write_bytes(b"tracked release archive")
    subprocess.run(["git", "add", "bundle.zip"], cwd=tmp_path, check=True)
    failed_report = tmp_path / "failed-report.json"
    failed = run_verifier(tmp_path, "ecosystem.json", failed_report)
    payload = json.loads(failed_report.read_text(encoding="utf-8"))
    assert failed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["errors"] == ["forbidden root artifacts: bundle.zip"]
