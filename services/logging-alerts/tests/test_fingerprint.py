import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_changing_ids_do_not_split_same_incident():
    code = """
from app.fingerprint import fingerprint
base = {"tenant_id": "t", "service": "api", "level": "ERROR"}
first = fingerprint({**base, "message": "request 123 failed"})
second = fingerprint({**base, "message": "request 456 failed"})
assert first == second
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE_ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
