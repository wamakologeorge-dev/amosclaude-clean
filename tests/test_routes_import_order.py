"""Regression guard for the applications <-> organizations circular import.

PR #1205 introduced a cycle: routes/__init__ imports ``applications`` before
``organizations``, while ``organizations`` imports ``applications`` at its
tail to merge application routes into its router. When ``applications`` also
imported organization helpers at module level, whichever module loaded first
handed the other a partially initialized module and the whole routes package
failed to import.

Each case runs in a fresh interpreter so ``sys.modules`` cannot mask ordering
bugs. Evidence over claim: these subprocesses actually execute the imports.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

CASES = {
    "package_first": "import amoscloud_ai.api.routes",
    "applications_first": (
        "import amoscloud_ai.api.routes.applications; import amoscloud_ai.api.routes"
    ),
    "organizations_first": (
        "import amoscloud_ai.api.routes.organizations; import amoscloud_ai.api.routes"
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_routes_import_is_order_safe(name: str) -> None:
    code = CASES[name] + "; print('IMPORT_OK')"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"{name} failed:\n{proc.stderr}"
    assert "IMPORT_OK" in proc.stdout
