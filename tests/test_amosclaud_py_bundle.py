"""Tests for the top-level Amosclaud.py bundle."""
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "Amosclaud.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("Amosclaud", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_builds_and_verifies():
    module = _load_module()
    bundle = module.build_bundle()
    assert bundle.name == "Amosclaud.py"
    assert bundle.verify() is True
    assert "bundle.verify" in bundle.capabilities


def test_manifest_detects_tampering():
    module = _load_module()
    bundle = module.build_bundle()
    manifest = bundle.manifest()
    assert bundle.verify_manifest(manifest) is True
    manifest["version"] = "tampered"
    assert bundle.verify_manifest(manifest) is False


def test_cli_describe_and_verify(capsys):
    module = _load_module()
    assert module.main(["describe"]) == 0
    assert '"name": "Amosclaud.py"' in capsys.readouterr().out
    assert module.main(["verify"]) == 0
    assert '"verified": true' in capsys.readouterr().out
