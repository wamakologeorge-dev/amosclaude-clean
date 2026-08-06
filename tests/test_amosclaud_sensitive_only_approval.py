import importlib.util
from pathlib import Path

from amosclaud_bot.approval_gate_v2 import (
    _high_risk_files,
    _is_authorized_autonomous_repair,
    _is_sensitive_objective,
    _patch_contains_sensitive_information,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_V2_PATH = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate_v2.py"


def _load_candidate_v2():
    spec = importlib.util.spec_from_file_location(
        "amosclaud_repair_candidate_v2_test",
        CANDIDATE_V2_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ordinary_repairs_do_not_require_approval() -> None:
    assert not _is_sensitive_objective("fix the deployment workflow")
    assert not _is_sensitive_objective("repair authentication tests")
    assert not _is_sensitive_objective("correct Docker infrastructure configuration")
    assert not _is_sensitive_objective("fix password validation and credential handling")


def test_environment_and_personal_data_repairs_require_approval() -> None:
    assert _is_sensitive_objective("repair the .env production configuration")
    assert _is_sensitive_objective("remove personal information from customer data")
    assert _is_sensitive_objective("rotate a leaked API key")


def test_sensitive_paths_and_content_are_detected() -> None:
    files = [
        {"filename": ".github/workflows/deploy.yml", "patch": "+name: Deploy"},
        {"filename": "src/service.py", "patch": "+result = 1"},
        {"filename": ".env.production", "patch": "+API_KEY=real-value"},
        {
            "filename": "data/customer.csv",
            "patch": "+social security: 123-45-6789",
        },
        {
            "filename": "src/config.py",
            "patch": '+API_KEY = "sk-1234567890abcdefghijkl"',
        },
    ]

    assert _high_risk_files(files) == [
        ".env.production",
        "data/customer.csv",
        "src/config.py",
    ]


def test_safe_placeholders_and_credential_code_do_not_trigger_approval() -> None:
    assert not _patch_contains_sensitive_information(
        "+API_KEY=example\n"
        "+PASSWORD=${PASSWORD}\n"
        "+token=os.getenv('TOKEN')\n"
        "+password = request.password\n"
        '+api_key = "settings.api_key"'
    )


def test_literal_secret_and_personal_values_trigger_approval() -> None:
    assert _patch_contains_sensitive_information('+password = "A-real-password-123"')
    assert _patch_contains_sensitive_information("+home address: 123 Private Street")


def test_trusted_approval_unlocks_env_repair(monkeypatch) -> None:
    candidate = _load_candidate_v2()

    monkeypatch.delenv("AMOSCLAUD_SENSITIVE_APPROVED", raising=False)
    assert candidate.protected_name(".env.production", [])

    monkeypatch.setenv("AMOSCLAUD_SENSITIVE_APPROVED", "true")
    assert not candidate.protected_name(".env.production", [])


def test_fork_origin_is_not_an_approval_boundary() -> None:
    pull_request = {
        "state": "open",
        "head": {"repo": {"full_name": "contributor/fork"}},
    }
    files = [{"filename": "src/service.py", "patch": "+return fixed"}]

    assert _is_authorized_autonomous_repair(pull_request, files)


def test_fork_with_personal_data_still_requires_approval() -> None:
    pull_request = {
        "state": "open",
        "head": {"repo": {"full_name": "contributor/fork"}},
    }
    files = [{"filename": "data/pii/customers.csv", "patch": "+name,address"}]

    assert not _is_authorized_autonomous_repair(pull_request, files)
