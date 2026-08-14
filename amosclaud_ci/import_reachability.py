"""Can the code a CI job runs actually import, using only what that job installs?

AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1 -- Amosclaud owns this check.

A test suite cannot answer this question about itself. The suite runs in an
environment that already has everything installed, so every import succeeds and
the run is green. A leaner job -- the fast pull-request lane, a release image, a
worker container -- installs a smaller dependency set, and the very same code
dies at import time with ``ModuleNotFoundError`` before a single test executes.

The trap that motivated this module is quiet and specific: importing
``package.module`` first executes ``package/__init__.py``. A module can import
nothing but the standard library and still be unimportable, because the package
it lives in imports the world on the way in. That is invisible to reading the
module, and invisible to any run on a machine where the world is installed.

This module answers the question statically, by walking what Python would
actually execute at import time.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

STDLIB: frozenset[str] = frozenset(sys.stdlib_module_names) | {"__future__"}

# Distributions whose install name differs from the name you import.
DISTRIBUTION_IMPORTS: dict[str, set[str]] = {
    "attrs": {"attr", "attrs"},
    "beautifulsoup4": {"bs4"},
    "charset-normalizer": {"charset_normalizer"},
    "flask-cors": {"flask_cors"},
    "gitpython": {"git"},
    "googleapis-common-protos": {"google"},
    "grpcio": {"grpc"},
    "mysqlclient": {"MySQLdb"},
    "opencv-python": {"cv2"},
    "pillow": {"PIL"},
    "protobuf": {"google"},
    "psycopg2-binary": {"psycopg2"},
    "pyjwt": {"jwt"},
    "pynacl": {"nacl"},
    "pyopenssl": {"OpenSSL"},
    "python-dateutil": {"dateutil"},
    "python-dotenv": {"dotenv"},
    "python-jose": {"jose"},
    "python-multipart": {"multipart"},
    "pyyaml": {"yaml", "_yaml"},
    "scikit-learn": {"sklearn"},
    "setuptools": {"setuptools", "pkg_resources"},
    "typing-extensions": {"typing_extensions"},
}

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)")


@dataclass(frozen=True)
class MissingImport:
    """A module that will not import under the declared dependency set."""

    entrypoint: str
    module: str
    line: int
    chain: tuple[str, ...]

    def format(self) -> str:
        route = " -> ".join(self.chain)
        return (
            f"{self.entrypoint}: needs '{self.module}', which the declared "
            f"dependencies do not provide (reached via {route}, line {self.line})"
        )


def normalise(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def parse_requirements(path: Path, _seen: set[Path] | None = None) -> set[str]:
    """Distribution names a requirements file declares, following ``-r`` links."""
    seen = _seen if _seen is not None else set()
    path = path.resolve()
    if path in seen or not path.exists():
        return set()
    seen.add(path)

    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            target = line.split(None, 1)[1].strip()
            names |= parse_requirements(path.parent / target, seen)
            continue
        if line.startswith("-"):
            continue  # -e ., --index-url, and other flags declare no module
        line = line.split(";", 1)[0]  # drop environment markers
        match = _REQUIREMENT_NAME.match(line)
        if match:
            names.add(normalise(match.group(1)))
    return names


def provided_modules(distributions: set[str]) -> set[str]:
    """Top-level import names a set of distributions makes available."""
    provided: set[str] = set()
    for dist in distributions:
        key = normalise(dist)
        provided |= DISTRIBUTION_IMPORTS.get(key, {key.replace("-", "_")})
    return provided


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    node = handler.type
    if node is None:
        return True  # bare except swallows everything, including ImportError
    candidates = node.elts if isinstance(node, ast.Tuple) else [node]
    for candidate in candidates:
        name = getattr(candidate, "id", None) or getattr(candidate, "attr", None)
        if name in {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}:
            return True
    return False


def import_time_imports(source: str) -> list[tuple[str, int, int]]:
    """Imports Python really executes when a module is imported.

    Returns ``(module, line, relative_level)``. Function bodies are excluded --
    they do not run on import. Class bodies are included, because they do.
    Imports guarded by ``try/except ImportError`` or ``if TYPE_CHECKING`` are
    excluded: the author already declared them optional or type-only.
    """
    tree = ast.parse(source)
    found: list[tuple[str, int, int]] = []

    def walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((alias.name, node.lineno, 0))
            elif isinstance(node, ast.ImportFrom):
                found.append((node.module or "", node.lineno, node.level))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # deferred until the function is called
            elif isinstance(node, ast.Try):
                if not any(_catches_import_error(h) for h in node.handlers):
                    walk(node.body)
                walk(node.orelse)
                walk(node.finalbody)
            elif isinstance(node, ast.If):
                if not _is_type_checking(node.test):
                    walk(node.body)
                walk(node.orelse)
            else:
                for field in ("body", "orelse", "finalbody"):
                    block = getattr(node, field, None)
                    if isinstance(block, list):
                        walk([s for s in block if isinstance(s, ast.stmt)])

    walk(tree.body)
    return found


def _package_of(path: Path, repo_root: Path) -> list[str]:
    parts = list(path.relative_to(repo_root).parts)
    return parts[:-1]


def resolve_local(module: str, repo_root: Path) -> list[Path]:
    """Files Python executes to import a repository-local module.

    Every parent package's ``__init__.py`` is included, because importing
    ``a.b.c`` runs ``a/__init__.py`` and ``a/b/__init__.py`` first. Missing that
    is precisely how a module with clean imports becomes unimportable.
    """
    if not module:
        return []
    parts = module.split(".")
    files: list[Path] = []
    current = repo_root
    for index, part in enumerate(parts):
        current = current / part
        init = current / "__init__.py"
        if init.exists():
            files.append(init)
        elif index < len(parts) - 1:
            return files  # not a package; stop descending
        if index == len(parts) - 1 and not init.exists():
            leaf = current.with_suffix(".py")
            if leaf.exists():
                files.append(leaf)
            elif not files:
                return []
    return files


def package_chain(entrypoint: Path, repo_root: Path) -> list[Path]:
    """``__init__.py`` files Python runs before the entrypoint, if it is in a package.

    ``python scripts/thing.py`` runs the file alone. ``import package.thing``
    runs ``package/__init__.py`` first. Which of the two applies is decided by
    the file's own location: a module sitting inside a package is reached by
    import, so the package's ``__init__`` is part of what executes.
    """
    parts = list(entrypoint.relative_to(repo_root).parts)[:-1]
    chain: list[Path] = []
    current = repo_root
    for part in parts:
        current = current / part
        init = current / "__init__.py"
        if not init.exists():
            return []  # plain directory, not a package: this is a script
        if init != entrypoint:
            chain.append(init)
    return chain


def analyse(
    entrypoint: Path,
    declared: set[str],
    repo_root: Path,
) -> list[MissingImport]:
    """Third-party modules an entrypoint reaches that ``declared`` cannot supply."""
    repo_root = repo_root.resolve()
    entrypoint = entrypoint.resolve()
    available = STDLIB | provided_modules(declared)

    missing: dict[str, MissingImport] = {}
    visited: set[Path] = set()
    queue: list[tuple[Path, tuple[str, ...]]] = []
    for init in package_chain(entrypoint, repo_root):
        queue.append((init, (str(init.relative_to(repo_root)),)))
    queue.append((entrypoint, (entrypoint.name,)))

    while queue:
        path, chain = queue.pop(0)
        if path in visited or not path.exists():
            continue
        visited.add(path)
        try:
            source = path.read_text(encoding="utf-8")
            imports = import_time_imports(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for module, line, level in imports:
            if level:  # relative import -- resolve against the containing package
                package = _package_of(path, repo_root)
                base = package[: len(package) - (level - 1)] if level > 1 else package
                module = ".".join([*base, module]) if module else ".".join(base)

            local = resolve_local(module, repo_root)
            if local:
                for target in local:
                    rel = str(target.relative_to(repo_root))
                    if target not in visited:
                        queue.append((target, (*chain, rel)))
                continue

            top = module.split(".")[0]
            if not top or top in available:
                continue
            key = f"{top}:{chain[-1]}"
            missing.setdefault(
                key,
                MissingImport(
                    entrypoint=str(entrypoint.relative_to(repo_root)),
                    module=top,
                    line=line,
                    chain=chain,
                ),
            )

    return sorted(missing.values(), key=lambda item: (item.module, item.chain))
