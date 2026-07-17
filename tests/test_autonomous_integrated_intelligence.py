from pathlib import Path

from src.amosclaud_os.kernel import AutonomousKernel


def test_model_and_connectors_belong_to_same_kernel(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)

    status = kernel.status()
    assert status["architecture"] == "single-autonomous-kernel"
    assert "model-response" in status["capabilities"]
    assert "documents" in status["capabilities"]

    response = kernel.model_respond(prompt="Build and test the website")
    assert response["source"] == "src.amosclaud_os.kernel.AutonomousKernel"
    assert response["failed"] is False


def test_read_write_is_governed_by_main_kernel(tmp_path: Path) -> None:
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


def test_failed_result_is_reported_not_hidden(tmp_path: Path) -> None:
    kernel = AutonomousKernel(tmp_path)
    result = kernel.model_respond(prompt="")
    assert result["failed"] is True
    assert result["error"] == "empty_prompt"
