from amosclaud_os.gateway.routing import is_engineering_command
from amosclaud_os.kernel.runtime import AmosclaudOSRuntime
from amosclaud_os.identity.permissions import allows


def test_runtime_remembers_platform_mission_and_roadmap() -> None:
    status = AmosclaudOSRuntime().status()
    assert "professional software engineer inside Amosclaud.com" in status.mission
    assert "Native workspace and persistent project context" in status.roadmap
    assert "repository" in status.services


def test_engineering_commands_route_to_execution() -> None:
    assert is_engineering_command("Create an issue for the login failure")
    assert is_engineering_command("Fix CI and verify the repository")
    assert not is_engineering_command("Explain only how CI works")


def test_native_permissions_are_explicit() -> None:
    assert allows("owner", "approve")
    assert allows("developer", "write")
    assert not allows("viewer", "write")
