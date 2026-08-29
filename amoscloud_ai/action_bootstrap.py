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
2. Installs the repository's canonical requirements manifests — the root
   ``requirements.txt``, the well-known dev/test manifests, the conventional
   ``requirements/`` folder, and the same names one directory down for
   monorepo services. Real repositories need their own dependencies — an api
   gateway needs its database driver — and pytest cannot even start when
   conftest imports are missing. This is the same contract every mainstream
   CI provides. Other ``*requirements*.txt`` variants are optional lanes a
   repository documents for special deployments (model servers, GPU images);
   they are skipped with a plain log line so a heavyweight optional lane can
   never break or bloat the test run. Tests that need an optional lane are
   expected to skip themselves when its packages are absent, which is exactly
   what ``pytest.importorskip`` is for. If a repository declares nothing
   canonical, every discovered manifest is installed so bespoke layouts still
   get an environment.
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
    """Partition discovered manifests into (install, skipped optional lanes).

    The fixed test environment installs what every mainstream CI installs:
    the canonical manifests (root ``requirements.txt``, the well-known
    dev/test names, the conventional ``requirements/`` folder, and the same
    canonical names one directory down for monorepo services). Any other
    ``*requirements*.txt`` variant is an optional lane the repository keeps
    separate on purpose — model servers, GPU builds, deployment bundles —
    and installing those can pull gigabyte-scale packages the tests never
    import. They are skipped, plainly logged. If nothing canonical exists,
    every discovered manifest is installed so bespoke layouts still work.
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

    canonical: list[Path] = []
    extras: list[Path] = []
    for path in candidates:
        conventional_folder = (
            path.parent.name == "requirements" and path.parent.parent == root
        )
        if path.name in CANONICAL_MANIFEST_NAMES or conventional_folder:
            canonical.append(path)
        else:
            extras.append(path)
    if not canonical:
        return candidates, []
    canonical.sort(
        key=lambda path: (len(path.parts), path.name != "requirements.txt", str(path))
    )
    return canonical, extras


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
            f"Skipping {extra.relative_to(root)}: optional requirements lanes are not "
            "part of the fixed test environment. Tests that need them should skip "
            "themselves when their packages are absent."
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
