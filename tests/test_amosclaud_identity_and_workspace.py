from pathlib import Path

from amoscloud_ai import (
    CANONICAL_AUTONOMOUS_PATH,
    LEGACY_IMPORT_NAMESPACE,
    PRODUCT_NAME,
    RUNTIME_NAME,
)
from amoscloud_ai.workspace_control import discover_layout, doctor


def test_runtime_identity_is_amosclaud_autonomous():
    assert PRODUCT_NAME == "Amosclaud"
    assert RUNTIME_NAME == "Amosclaud Autonomous"
    assert CANONICAL_AUTONOMOUS_PATH == "/autonomous"
    assert LEGACY_IMPORT_NAMESPACE == "amoscloud_ai"
    assert "cloud" not in RUNTIME_NAME.lower()


def test_repository_workspace_uses_unified_compose_contract():
    layout = discover_layout(Path.cwd())
    assert layout.compose_file == Path.cwd() / "Infrastructure" / "docker-compose.yml"

    report = doctor(layout)
    contract = report["platform_contract"]
    assert all(contract["services"].values())
    assert all(contract["required_environment"].values())
    assert contract["autonomous_enabled"] is True
    assert contract["fixer_enabled"] is True
    assert contract["verification_required"] is True
    assert contract["default_branch_protected"] is True
