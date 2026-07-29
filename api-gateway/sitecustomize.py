"""Load the repository endpoint guard for the standalone API gateway."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT_GUARD = Path(__file__).resolve().parents[1] / "sitecustomize.py"
_SPEC = importlib.util.spec_from_file_location("_amosclaud_repository_sitecustomize", _ROOT_GUARD)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load Amosclaud endpoint guard: {_ROOT_GUARD}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
