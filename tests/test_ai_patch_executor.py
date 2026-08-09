from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "ai_patch_executor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ai_patch_executor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_executor_is_retired_and_fail_closed(tmp_path: Path) -> None:
    module = load_module()
    report = tmp_path / "report.json"

    status = module.main(["--report", str(report)])

    assert status == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "NATIVE_OLLAMA_REPAIR_REQUIRED"
    assert payload["provider"] == "amosclaud-native-ollama"
    assert payload["patch_applied"] is False
    assert payload["commit_allowed"] is False
    assert payload["push_allowed"] is False


def test_executor_module_contains_no_external_model_client() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "api.anthropic.com" not in source
    assert "ANTHROPIC_API_KEY" not in source
    assert "urllib.request" not in source
    assert "read_text(encoding=\"utf-8\", errors=\"replace\")" not in source
    assert "git push" not in source
    assert "git commit" not in source
