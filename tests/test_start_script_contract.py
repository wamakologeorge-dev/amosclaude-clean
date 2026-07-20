from pathlib import Path


START_SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "start.sh"


def test_start_script_uses_canonical_platform_app() -> None:
    text = START_SCRIPT.read_text(encoding="utf-8")
    assert 'AMOSCLAUD_APP_MODULE:-amoscloud_ai.main:app' in text
    assert 'from amoscloud_ai.main import app' in text
    assert '"/health", "/api/v1/agent/run"' in text
    assert "src.server.main" not in text
    assert "Amosclaud.Amosclaud" not in text


def test_start_script_is_location_independent_and_checks_storage() -> None:
    text = START_SCRIPT.read_text(encoding="utf-8")
    assert 'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"' in text
    assert 'python "$PROJECT_ROOT/scripts/check_persistence.py"' in text
    assert 'export AUTH_DB_PATH=' in text
    assert 'export REPOSITORY_STORAGE_PATH=' in text
    assert 'export AMOSCLAUD_STORAGE_PATH=' in text
    assert 'export AMOSCLAUD_MODEL_HOME=' in text


def test_start_script_validates_runtime_values() -> None:
    text = START_SCRIPT.read_text(encoding="utf-8")
    assert "PORT must be between 1 and 65535" in text
    assert "WORKERS must be at least 1" in text
    assert 'FORWARDED_ALLOW_IPS:-*' in text
