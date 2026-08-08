import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_retry_is_bounded():
    code = """
from app.retry import RetryPolicy
policy = RetryPolicy(max_attempts=3, base_delay_seconds=1, maximum_delay_seconds=3)
assert policy.delay(1) == 1
assert policy.delay(3) == 3
assert policy.delay(99) == 3
assert policy.should_dead_letter(3)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE_ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
