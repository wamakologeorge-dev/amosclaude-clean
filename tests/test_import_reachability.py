"""Tests for Amosclaud's import-reachability analyser."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from amosclaud_ci.import_reachability import (
    analyse,
    import_time_imports,
    package_chain,
    parse_requirements,
    provided_modules,
    resolve_local,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# --------------------------------------------------------------- requirements


def test_parse_requirements_reads_names_markers_extras_and_includes(tmp_path):
    write(tmp_path, "base.txt", "requests>=2\n# a comment\nuvicorn[standard]<1\n")
    write(
        tmp_path,
        "dev.txt",
        """
        -r base.txt
        -e .
        --index-url https://example.invalid/simple
        PyYAML>=6.0,<7

        pytest ; python_version >= "3.9"
        """,
    )
    assert parse_requirements(tmp_path / "dev.txt") == {
        "requests",
        "uvicorn",
        "pyyaml",
        "pytest",
    }


def test_provided_modules_knows_install_names_differ_from_import_names():
    provided = provided_modules({"PyYAML", "python-dateutil", "beautifulsoup4", "pytest"})
    assert {"yaml", "dateutil", "bs4", "pytest"} <= provided
    # The install name itself must not be mistaken for an import name.
    assert "pyyaml" not in provided


# ------------------------------------------------------------- what executes


def test_only_imports_that_actually_run_on_import_are_collected():
    modules = {name for name, _line, _level in import_time_imports(textwrap.dedent("""
                import at_module_level
                from typing import TYPE_CHECKING

                if TYPE_CHECKING:
                    import only_for_type_checkers

                try:
                    import optional_extra
                except ImportError:
                    optional_extra = None

                class Thing:
                    import inside_class_body

                def later():
                    import deferred_until_called
                """))}
    assert "at_module_level" in modules
    assert "inside_class_body" in modules, "class bodies run at import time"
    assert "deferred_until_called" not in modules, "function bodies do not"
    assert "only_for_type_checkers" not in modules, "TYPE_CHECKING blocks do not run"
    assert "optional_extra" not in modules, "the author already handled its absence"


def test_bare_except_also_marks_an_import_optional():
    modules = {
        n for n, _l, _lv in import_time_imports("try:\n    import maybe\nexcept:\n    pass\n")
    }
    assert "maybe" not in modules


# ------------------------------------------------------ package init chaining


def test_resolve_local_includes_every_parent_package_init(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/sub/__init__.py", "")
    write(tmp_path, "pkg/sub/leaf.py", "")
    resolved = [str(p.relative_to(tmp_path)) for p in resolve_local("pkg.sub.leaf", tmp_path)]
    assert resolved == ["pkg/__init__.py", "pkg/sub/__init__.py", "pkg/sub/leaf.py"]


def test_package_chain_separates_a_script_from_a_package_module(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    module = write(tmp_path, "pkg/thing.py", "")
    script = write(tmp_path, "bin/tool.py", "")
    assert [p.name for p in package_chain(module, tmp_path)] == ["__init__.py"]
    assert package_chain(script, tmp_path) == [], "a plain directory is not a package"


# ------------------------------------------------------------- the real thing


def test_a_module_with_clean_imports_is_still_unimportable_through_a_heavy_package(tmp_path):
    """The defect this analyser exists for.

    ``pkg/leaf.py`` imports nothing but the standard library, so reading it
    suggests it is safe anywhere. Importing ``pkg.leaf`` runs
    ``pkg/__init__.py`` first, which needs a dependency the lean job does not
    install. The module is unimportable despite being clean.
    """
    write(tmp_path, "pkg/__init__.py", "import fastapi\n")
    leaf = write(tmp_path, "pkg/leaf.py", "import json\nimport yaml\n")
    write(tmp_path, "reqs.txt", "PyYAML>=6\n")

    declared = parse_requirements(tmp_path / "reqs.txt")
    missing = {finding.module for finding in analyse(leaf, declared, tmp_path)}

    assert missing == {"fastapi"}, "the parent package's import must be counted"


def test_a_script_outside_a_package_does_not_inherit_that_burden(tmp_path):
    write(tmp_path, "pkg/__init__.py", "import fastapi\n")
    script = write(tmp_path, "bin/tool.py", "import json\n")
    assert analyse(script, set(), tmp_path) == []


def test_declared_dependencies_satisfy_their_imports(tmp_path):
    entry = write(tmp_path, "bin/tool.py", "import yaml\nimport websockets\n")
    write(tmp_path, "reqs.txt", "PyYAML>=6\nwebsockets>=12\n")
    assert analyse(entry, parse_requirements(tmp_path / "reqs.txt"), tmp_path) == []


def test_transitive_local_imports_are_followed(tmp_path):
    write(tmp_path, "a.py", "import b\n")
    write(tmp_path, "b.py", "import c\n")
    write(tmp_path, "c.py", "import nowhere_at_all\n")
    findings = analyse(tmp_path / "a.py", set(), tmp_path)
    assert [f.module for f in findings] == ["nowhere_at_all"]
    assert findings[0].chain[-1] == "c.py", "the report names the file that needs it"


# ------------------------------------------------- agreement with a real venv


def test_analyser_agrees_with_a_real_interpreter(tmp_path):
    """Build a real environment, then check the prediction against reality."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=300)
    python = venv / "bin" / "python"
    if not python.exists():  # pragma: no cover - non-POSIX layout
        python = venv / "Scripts" / "python.exe"

    project = tmp_path / "project"
    write(project, "pkg/__init__.py", "import yaml\n")
    leaf = write(project, "pkg/leaf.py", "import json\n")
    write(project, "reqs.txt", "")

    predicted = {f.module for f in analyse(leaf, parse_requirements(project / "reqs.txt"), project)}

    actual = subprocess.run(
        [str(python), "-c", "import pkg.leaf"],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert actual.returncode != 0, "the empty environment really is missing yaml"
    assert "yaml" in actual.stderr
    assert predicted == {"yaml"}, f"prediction {predicted} disagreed with the interpreter"


# ------------------------------------------------------------ this repository


def test_the_fast_lane_guard_imports_under_the_fast_lane_dependencies():
    """Regression guard for a real defect that shipped.

    ``scripts/ci/workflow_validator_guard.py`` once imported its validator
    through ``amosclaud_bot``, whose ``__init__`` pulls in FastAPI. The fast
    lane does not install FastAPI, so the gate would have crashed. Every local
    check passed, because the development machine had FastAPI installed.
    """
    declared = parse_requirements(REPO_ROOT / "requirements-ci-fast.txt")
    guard = REPO_ROOT / "scripts" / "ci" / "workflow_validator_guard.py"
    if not guard.exists():  # pragma: no cover - guard lands with the validator
        return
    findings = analyse(guard, declared, REPO_ROOT)
    assert findings == [], "\n".join(f.format() for f in findings)
