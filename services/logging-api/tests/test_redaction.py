import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _run(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE_ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_nested_secrets_are_removed():
    _run("""
from app.redaction.service import redact
value = {"authorization": "Bearer secret-value", "nested": {"api_key": "abc"}}
assert redact(value) == {"authorization": "[REDACTED]", "nested": {"api_key": "[REDACTED]"}}
""")


def test_tokens_inside_messages_are_removed():
    _run("""
from app.redaction.service import redact
output = redact({"message": "Authorization Bearer abcdefghijklmnop"})
assert "abcdefghijklmnop" not in output["message"]
""")
