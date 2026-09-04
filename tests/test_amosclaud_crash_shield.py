from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "amosclaud_crash_shield.py"
spec = importlib.util.spec_from_file_location("amosclaud_crash_shield", MODULE_PATH)
assert spec and spec.loader
shield = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shield)


def _python_findings(tmp_path: Path, source: str):
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    return shield.scan_python(path, tmp_path)


def test_flags_module_environment_lookup_that_can_break_startup(tmp_path: Path):
    findings = _python_findings(tmp_path, "import os\nTOKEN = os.environ['TOKEN']\n")
    assert any(item.rule == "PY001" and item.line == 2 for item in findings)


def test_flags_process_exit(tmp_path: Path):
    findings = _python_findings(tmp_path, "import sys\ndef stop():\n    sys.exit(1)\n")
    assert any(item.rule == "PY004" and item.severity == "critical" for item in findings)


def test_flags_network_call_without_timeout(tmp_path: Path):
    findings = _python_findings(tmp_path, "import requests\ndef load():\n    return requests.get('https://example.invalid')\n")
    assert any(item.rule == "PY006" for item in findings)


def test_network_timeout_removes_warning(tmp_path: Path):
    findings = _python_findings(tmp_path, "import requests\ndef load():\n    return requests.get('https://example.invalid', timeout=10)\n")
    assert not any(item.rule == "PY006" for item in findings)


def test_flags_syntax_error_as_critical(tmp_path: Path):
    findings = _python_findings(tmp_path, "def broken(:\n    pass\n")
    assert findings[0].rule == "PY000"
    assert findings[0].severity == "critical"


def test_flags_node_process_exit(tmp_path: Path):
    path = tmp_path / "server.mjs"
    path.write_text("if (fatal) process.exit(1);\n", encoding="utf-8")
    findings = shield.scan_javascript(path, tmp_path)
    assert any(item.rule == "JS001" for item in findings)
