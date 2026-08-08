import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_query_is_tenant_scoped_and_parameterized():
    code = """
from app.filters import build_log_query
sql, values = build_log_query("tenant-a", level="ERROR", search="boom", limit=25)
assert "tenant_id = $1" in sql
assert "level = $2" in sql
assert "message ILIKE $3" in sql
assert values == ["tenant-a", "ERROR", "%boom%", 25]
assert "boom" not in sql
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE_ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
