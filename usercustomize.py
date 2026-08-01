"""Ensure repository endpoint guards are available even when system sitecustomize loads first."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_SITECUSTOMIZE = Path(__file__).resolve().parent / "sitecustomize.py"
_SPEC = importlib.util.spec_from_file_location("_amosclaud_repository_sitecustomize", _REPO_SITECUSTOMIZE)

if _SPEC is not None and _SPEC.loader is not None:
    _MODULE = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_MODULE)
    _SYSTEM_MODULE = sys.modules.get("sitecustomize")
    if _SYSTEM_MODULE is not None:
        for _name in ("normalize_public_amosclaud_url", "normalize_public_environment"):
            if hasattr(_MODULE, _name):
                setattr(_SYSTEM_MODULE, _name, getattr(_MODULE, _name))
