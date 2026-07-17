from pathlib import Path

from src.amosclaud_os.kernel import AutonomousKernel, get_autonomous_kernel


def test_kernel_singleton_per_workspace(tmp_path: Path):
    first = get_autonomous_kernel(tmp_path)
    second = get_autonomous_kernel(tmp_path)
    assert first is second
    status = first.status()
    assert status["product"] == "Amosclaud OS"
    assert status["driver"] == "Amosclaud Autonomous"
    assert status["architecture"] == "single-autonomous-kernel"


def test_kernel_status_uses_canonical_source(tmp_path: Path):
    kernel = AutonomousKernel(tmp_path)
    status = kernel.status()
    assert status["status"] == "ready"
    assert status["single_source"] == "src.amosclaud_os.kernel.AutonomousKernel"
    assert "engineering-loop" in status["entry_points"]
    assert "recovery-doctor" in status["entry_points"]
