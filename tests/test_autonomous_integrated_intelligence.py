from pathlib import Path

from src.amosclaud_os.kernel import AutonomousKernel


def test_model_and_connectors_belong_to_same_autonomous(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)

    status = kernel.status()
    assert status["architecture"] == "one-autonomous-agent"
    assert status["product_areas"] == ["autonomous", "repository", "results"]
    assert status["public_agents"] == ["Amosclaud Autonomous"]
    assert "model-response" in status["capabilities"]
    assert "documents" in status["capabilities"]

    response = kernel.model_respond(prompt="Build and test the website")
    assert response["source"] == "src.amosclaud_os.kernel.AutonomousKernel"
    assert response["agent"] == "Amosclaud Autonomous"
    assert response["agent_identity"] == "one-agent"
    assert response["failed"] is False


def test_read_write_is_governed_by_same_autonomous(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)

    denied = kernel.write_document("result.txt", "hello")
    assert denied["ok"] is False
    assert denied["error"] == "write_not_authorized"

    written = kernel.write_document(
        "result.txt", "hello", authorized_writes=True
    )
    assert written["ok"] is True

    read = kernel.read_document("result.txt")
    assert read["ok"] is True
    assert read["content"] == "hello"
    assert read["agent"] == written["agent"] == "Amosclaud Autonomous"


def test_failed_result_is_reported_not_hidden(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)
    result = kernel.run(objective="", repository="demo")

    assert result["results"]["status"] == "failed"
    assert result["results"]["failed"] is True
    assert result["results"]["error"] == "empty_objective"


def test_public_contract_has_only_three_product_areas(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)
    result = kernel.run(objective="Inspect the repository", repository="demo")

    assert set(result) == {"autonomous", "repository", "results"}
    assert result["autonomous"]["name"] == "Amosclaud Autonomous"
    assert result["autonomous"]["identity"] == "one-agent"
    assert result["repository"]["name"] == "demo"
    assert result["repository"]["writes_authorized"] is False
    assert "raw" not in result["results"]
    assert result["results"]["source"] == "src.amosclaud_os.kernel.AutonomousKernel"


def test_write_capability_requires_explicit_authorization(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)

    blocked = kernel.run(
        objective="Fix the failing test",
        mode="fix",
        repository="demo",
    )

    assert blocked["results"]["status"] == "blocked"
    assert blocked["results"]["blocked"] is True
    assert blocked["results"]["failed"] is False
    assert blocked["results"]["error"] == "write_not_authorized"
    assert blocked["autonomous"]["name"] == "Amosclaud Autonomous"


def test_authorized_fix_uses_same_autonomous_execution_path(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)
    result = kernel.repair(
        issue="Fix the failing test",
        authorized_writes=True,
    )

    assert result["agent"] == "Amosclaud Autonomous"
    assert result["agent_identity"] == "one-agent"
    assert result["system_identity"]["architecture"] == "one-autonomous-agent"


def test_result_normalization_does_not_call_a_plan_completed() -> None:
    assert AutonomousKernel._result_status({"status": "planning"}) == "planned"
    assert AutonomousKernel._result_status({"status": "blocked"}) == "blocked"
    assert AutonomousKernel._result_status({"status": "failed"}) == "failed"
    assert AutonomousKernel._result_status({"status": "passed"}) == "completed"
