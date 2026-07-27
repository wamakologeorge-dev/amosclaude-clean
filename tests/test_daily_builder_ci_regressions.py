"""Regression contracts for failures exposed after Daily Builder merge."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from amoscloud_ai.main import create_app


def test_live_github_pull_request_feed_is_mounted_directly() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/github/repositories/{repository_id}/pull-requests" in paths

    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")
    assert "github_pull_requests," in source
    assert "app.include_router(github_pull_requests.router, prefix=\"/api/v1\")" in source


def test_routes_package_has_no_heavy_dispatch_import_side_effect() -> None:
    source = Path("amoscloud_ai/api/routes/__init__.py").read_text(encoding="utf-8")
    assert "install_dispatch_hook" not in source
    assert "autonomous_task_runner" not in source


def test_cmood_and_kernel_import_without_a_circular_dependency() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import cmood; import shared; import src.amosclaud_os.kernel",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
