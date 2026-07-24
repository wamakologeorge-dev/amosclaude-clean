from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_autonomous_codex_uses_amosclaud_owned_gateway() -> None:
    config = tomllib.loads((ROOT / "config" / "autonomous-codex.toml").read_text(encoding="utf-8"))

    assert config["model"]["provider"] == "amosclaud"
    assert config["model"]["api_key_env"] == "AMOSCLAUD_API_KEY"
    assert config["model"]["base_url_env"] == "AMOSCLAUD_API_URL"
    assert config["credentials"]["allow_provider_keys"] is False
    assert "OPENAI_API_KEY" not in (ROOT / "config" / "autonomous-codex.toml").read_text(
        encoding="utf-8"
    )


def test_autonomous_writes_require_authorization_and_isolation() -> None:
    config = tomllib.loads((ROOT / "config" / "autonomous-codex.toml").read_text(encoding="utf-8"))

    assert config["permissions"]["auto_approve_write"] is False
    assert config["permissions"]["require_explicit_write_authorization"] is True
    assert config["workspace"]["allow_outside_workspace"] is False
    assert config["workspace"]["require_repository_connector"] is True
    assert config["repository"]["require_isolated_worktree"] is True
    assert config["repository"]["protect_default_branch"] is True
    assert config["repository"]["allow_direct_default_branch_write"] is False


def test_success_requires_verification_evidence() -> None:
    config = tomllib.loads((ROOT / "config" / "autonomous-codex.toml").read_text(encoding="utf-8"))
    verification = config["verification"]

    assert verification["require_tests_for_code_changes"] is True
    assert verification["require_clean_diff_review"] is True
    assert verification["require_verification_id"] is True
    assert verification["require_commit_sha"] is True
    assert verification["require_changed_files"] is True
    assert verification["success_requires_all_checks"] is True


def test_os_manifest_names_unified_platform_services() -> None:
    manifest = (ROOT / "config" / "amosclaud-os.yaml").read_text(encoding="utf-8")

    for required in (
        "name: Amosclaud OS",
        "command_entrypoint: python -m amosclaud_platform",
        "repository: repository.connector.RepositoryConnector",
        "credentials: api_key_manager",
        "metrics: amosclaud_metrics",
        "model_workspace: model-workspace",
        "explicit_write_authorization_required: true",
        "provider_keys_allowed: false",
    ):
        assert required in manifest


def test_bootstrap_does_not_request_external_provider_key() -> None:
    bootstrap = (ROOT / "amoscloud_ai" / "agent" / "bootstrap.py").read_text(encoding="utf-8")

    assert "AMOSCLAUD_API_KEY" in bootstrap
    assert "AMOSCLAUD_API_URL" in bootstrap
    assert "OPENAI_API_KEY" not in bootstrap
