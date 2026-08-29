"""Prepare a native Action checkout: build the repository's own environment.

This file is copied verbatim into every disposable Action checkout and executed
there as a fixed, code-owned plan step. It is intentionally self-contained
(standard library only) because it runs inside the isolated worker sandbox
where the Amosclaud platform packages are not importable.

What it does, truthfully and in order:

1. Builds a fresh virtual environment at ``.amosclaud-venv`` inside the
   checkout. Any same-named directory committed to the repository is deleted
   first, so repository content can never impersonate the environment. The
   environment can see the worker station's baseline toolkit (pytest and its
   canonical plugins), while packages installed here take precedence.
2. Installs the repository's canonical requirements manifests. Real
   repositories need their own dependencies — an api gateway needs its
   database driver — and pytest cannot even start when conftest imports are
   missing. This is the same contract every mainstream CI provides, and like
   mainstream CI the plan installs the *authoritative* declaration rather
   than every requirements file in sight: root-level manifests (the root
   ``requirements.txt``, well-known dev/test names, the conventional
   ``requirements/`` folder) alone define the test environment when they
   exist. Nested service manifests and optional variant lanes (model
   servers, GPU images, deployment bundles) are separate lanes — installing
   them can pull gigabyte-scale packages the tests never import, reference
   paths that only exist in that service's own context, or silently
   downgrade the root environment's pins — so they are skipped with a plain
   log line. Tests that need an optional lane are expected to skip
   themselves when its packages are absent, which is exactly what
   ``pytest.importorskip`` is for. A repository with no root-level manifests
   falls back to canonical names one directory down, and one with nothing
   canonical at all falls back to every discovered manifest, so bespoke
   layouts still get an environment.
3. Optionally installs the repository package itself (editable) when the
   repository declares a build (``pyproject.toml`` or ``setup.py``). A failure
   here is reported but not fatal: the authoritative verdict belongs to the
   pytest step, whose log will show plainly whether the tests needed it.

It never inspects or executes repository-controlled command configuration;
the only inputs honored are standard Python packaging manifests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

VENV_DIR = ".amosclaud-venv"

_PIP_ENV = {
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_CACHE_DIR": "1",
    "PIP_NO_INPUT": "1",
    "PIP_ROOT_USER_ACTION": "ignore",
    "PYTHONDONTWRITEBYTECODE": "1",
}

CANONICAL_MANIFEST_NAMES = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements-tests.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
)


def _discover_manifests(root: Path) -> tuple[list[Path], list[Path]]:
    """Partition discovered manifests into (install, skipped separate lanes).

    Tier 1 — root-level declarations: the root canonical names plus the
    conventional ``requirements/`` folder. When any exist they alone define
    the test environment, exactly like the manifests a mainstream CI workflow
    names explicitly. Tier 2 — canonical names one directory down, used only
    when the root declares nothing (a monorepo of services without a root
    manifest). Tier 3 — every discovered ``*requirements*.txt``, used only
    when nothing canonical exists anywhere. Everything outside the selected
    tier is skipped and plainly logged: nested service manifests can
    reference paths that only exist in their own context or downgrade the
    root environment's pins, and optional variant lanes (model servers, GPU
    builds) can pull gigabyte-scale packages the tests never import.
    """

    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            candidates.append(path)

    for pattern in ("*requirements*.txt", "*/*requirements*.txt"):
        for path in sorted(root.glob(pattern)):
            if VENV_DIR in path.parts:
                continue
            _add(path)
    requirements_dir = root / "requirements"
    if requirements_dir.is_dir():
        for path in sorted(requirements_dir.glob("*.txt")):
            _add(path)

    def _tier(path: Path) -> int:
        at_root = path.parent == root
        conventional_folder = (
            path.parent.name == "requirements" and path.parent.parent == root
        )
        if conventional_folder or (at_root and path.name in CANONICAL_MANIFEST_NAMES):
            return 1
        if not at_root and path.name in CANONICAL_MANIFEST_NAMES:
            return 2
        return 3

    best = min((_tier(path) for path in candidates), default=3)
    if best == 3:
        return candidates, []
    install = [path for path in candidates if _tier(path) == best]
    skipped = [path for path in candidates if _tier(path) != best]
    install.sort(
        key=lambda path: (len(path.parts), path.name != "requirements.txt", str(path))
    )
    return install, skipped


def _requirement_files(root: Path) -> list[Path]:
    """The manifests the fixed plan installs (see ``_discover_manifests``)."""

    return _discover_manifests(root)[0]


def _run_pip(python: Path, arguments: list[str]) -> int:
    env = dict(os.environ)
    env.update(_PIP_ENV)
    completed = subprocess.run(  # noqa: S603 — fixed argv, never a shell
        [str(python), "-m", "pip", *arguments],
        env=env,
        check=False,
    )
    return int(completed.returncode)


def main() -> int:
    root = Path.cwd()
    venv_path = root / VENV_DIR
    if venv_path.exists():
        print(f"Removing a committed {VENV_DIR} directory; the Action always builds a fresh one.")
        shutil.rmtree(venv_path)

    swept = False
    for pycache in list(root.rglob("__pycache__")):
        if VENV_DIR in pycache.parts or ".git" in pycache.parts:
            continue
        shutil.rmtree(pycache, ignore_errors=True)
        swept = True
    for stray in list(root.rglob("*.pyc")):
        if VENV_DIR in stray.parts or ".git" in stray.parts:
            continue
        try:
            stray.unlink()
            swept = True
        except OSError:
            pass
    if swept:
        print(
            "Removed the compile step's bytecode byproduct so the tests see the "
            "same pristine tree a fresh clone provides."
        )

    print(
        f"Creating the Action environment at {VENV_DIR} "
        "(worker toolkit visible; repository packages take precedence)."
    )
    venv.EnvBuilder(system_site_packages=True, with_pip=True, clear=True).create(str(venv_path))
    python = venv_path / "bin" / "python"
    if not python.exists():
        print("The Action environment has no python executable; the worker station is misconfigured.")
        return 1

    manifests, skipped = _discover_manifests(root)
    for extra in skipped:
        print(
            f"Skipping {extra.relative_to(root)}: the repository's canonical manifests "
            "define the Action environment and other requirements files are separate "
            "lanes. Tests that need them should skip themselves when their packages "
            "are absent."
        )
    if not manifests:
        print("No requirements manifests found; the worker toolkit alone will run the tests.")
    for manifest in manifests:
        relative = manifest.relative_to(root)
        print(f"Installing {relative} into the Action environment.")
        code = _run_pip(python, ["install", "-q", "-r", str(relative)])
        if code != 0:
            print(
                f"pip could not install {relative} (exit {code}). "
                "The messages above record the exact cause."
            )
            return code

    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        print("Installing the repository package itself (editable).")
        code = _run_pip(python, ["install", "-q", "-e", "."])
        if code != 0:
            print(
                f"Warning: the repository package did not install (exit {code}); continuing. "
                "If the tests need it, the pytest step will say so plainly."
            )

    print("Repository environment ready for the fixed pytest step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
