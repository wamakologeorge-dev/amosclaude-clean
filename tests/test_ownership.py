from src.core.ci_orchestrator import CIOrchestrator
from src.ownership import AMOSCLAUD_OWNERSHIP, get_ownership_profile


def test_get_ownership_profile_returns_deep_copy():
    profile = get_ownership_profile()

    profile["coverage"]["frontend"]["owner"] = "Someone Else"

    assert AMOSCLAUD_OWNERSHIP["coverage"]["frontend"]["owner"] == "Amosclaud"


def test_ci_orchestrator_status_includes_amosclaud_owner():
    status = CIOrchestrator({}).get_status()

    assert status["owner"] == "Amosclaud"
    assert status["ownership"]["coverage"]["ai_power"]["owner"] == "Amosclaud"
