"""Repository-wide pytest configuration.

Keep test runs from generating Python bytecode inside the source tree.

The Amosclaud namespace contract
(tests/test_amosclaud_namespace_contract.py) requires that no ``*.pyc``
files or ``__pycache__`` directories exist under ``Amosclaud/``. Importing
the compatibility package during the test session would otherwise write
bytecode there mid-run. CircleCI already exports
``PYTHONDONTWRITEBYTECODE=1``; this conftest applies the same guarantee to
every environment that runs pytest.
"""

import sys
import importlib.util
import os
from pathlib import Path

sys.dont_write_bytecode = True


def _ensure_repository_sitecustomize_exports() -> None:
    root = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "_amosclaud_repository_sitecustomize",
        root / "sitecustomize.py",
    )
    if spec is None or spec.loader is None:
        return

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    system_module = sys.modules.get("sitecustomize")
    if system_module is None:
        sys.modules["sitecustomize"] = module
    else:
        for name in ("normalize_public_amosclaud_url", "normalize_public_environment"):
            setattr(system_module, name, getattr(module, name))

    existing = os.environ.get("PYTHONPATH", "")
    root_path = str(root)
    if not existing:
        os.environ["PYTHONPATH"] = root_path
    elif root_path not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = f"{root_path}{os.pathsep}{existing}"


_ensure_repository_sitecustomize_exports()
