from pathlib import Path


def test_amosclaud_compatibility_entry_point_uses_canonical_platform_app():
    from Amosclaud.Amosclaud import app as compatibility_app
    from amoscloud_ai.main import app as canonical_app

    compatibility_paths = {getattr(route, "path", "") for route in compatibility_app.routes}
    canonical_paths = {getattr(route, "path", "") for route in canonical_app.routes}

    assert "/api/v1/agent/run" in compatibility_paths
    assert compatibility_paths == canonical_paths


def test_amosclaud_namespace_does_not_track_generated_python_bytecode():
    root = Path(__file__).resolve().parents[1] / "Amosclaud"
    assert not list(root.rglob("*.pyc"))
    assert not list(root.rglob("__pycache__"))


def test_amosclaud_package_exposes_lazy_platform_factories():
    import Amosclaud

    assert callable(Amosclaud.create_platform_app)
    assert callable(Amosclaud.create_platform_byte_bus)
