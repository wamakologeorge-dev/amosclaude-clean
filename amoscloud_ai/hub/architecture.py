"""Visual Architecture Mapper.

Scans a repository working tree and describes its structure as a **Mermaid**
diagram plus deterministic Markdown. Mermaid renders natively in GitHub
Markdown and in the platform's own viewer, so this phase needs no image
pipeline, no external service and — deliberately — **no model call at all**.
Every value produced here is counted or parsed from source text, so the same
tree always yields the same map.

Analysis is static only
-----------------------
Scanned code is never imported, executed or evaluated. Python files are read
as text and parsed with :func:`ast.parse`; a file that fails to parse is
skipped and reported in :attr:`ArchitectureMap.skipped`, never raised. The
scan is bounded by :data:`MAX_FILES`, :data:`MAX_TOTAL_BYTES` and
:data:`MAX_FILE_BYTES`, and sets :attr:`ArchitectureMap.truncated` when a cap
is reached, in the same spirit as :mod:`amoscloud_ai.hub.report`.

What it detects
---------------
* **Top-level Python units** — every directory holding an ``__init__.py`` and
  every top-level ``*.py`` module — with the import edges between them.
* **FastAPI route surface** — ``APIRouter`` assignments with literal
  ``prefix``/``tags``, the ``@router.<method>("/path")`` decorators attached to
  them, and the ``include_router(<module>.<var>, prefix=...)`` mounts that give
  a route its full URL (the platform mounts everything in
  ``amoscloud_ai/main.py``).
* **SQLite tables** — names following a literal ``CREATE TABLE`` in Python
  source text.

Known limits are recorded in :attr:`ArchitectureMap.notes` rather than hidden:
only literal values are read, so a prefix or path built at runtime is not
resolved, and a route whose router variable was never assigned an
``APIRouter`` in the same module is not attributed.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from amoscloud_ai.hub.report import escape_cell
from amoscloud_ai.markdown_service import MarkdownDocument, render_markdown_document

#: Hard ceiling on the number of files opened by one scan.
MAX_FILES = 1_500

#: Hard ceiling on the total bytes read by one scan.
MAX_TOTAL_BYTES = 12_000_000

#: Files larger than this are skipped rather than parsed.
MAX_FILE_BYTES = 1_000_000

#: Directories never entered: version control, caches, vendored and built code.
SKIP_DIRECTORIES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
        "vendor",
    }
)

#: Nodes and edges drawn in one diagram. Beyond this the diagram stops being
#: readable, so it is trimmed deterministically and the trim is reported.
MAX_DIAGRAM_NODES = 40
MAX_DIAGRAM_EDGES = 120

#: Rows rendered in the Markdown route table.
MAX_ROUTE_ROWS = 200

#: Rows rendered in the Markdown table listing.
MAX_TABLE_ROWS = 120

#: Skipped files listed in the Markdown.
MAX_SKIPPED_ROWS = 40

#: Longest Mermaid node label kept before truncation.
MAX_LABEL_CHARACTERS = 80

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)

#: Table names are read from literal ``CREATE TABLE`` text. The negative
#: lookahead stops the optional ``IF NOT EXISTS`` clause from being captured as
#: the table name when the real name is an f-string placeholder such as
#: ``CREATE TABLE IF NOT EXISTS {table}`` — a dynamic name is reported as no
#: table rather than as a table called ``IF``.
_CREATE_TABLE = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"[\"'`\[]?(?!(?:IF|NOT|EXISTS|TEMP|TEMPORARY|TABLE)\b)(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_NON_IDENTIFIER = re.compile(r"[^A-Za-z0-9]+")

# Characters allowed inside a Mermaid node label. Everything else — including
# ``"``, ``#``, ``;``, ``[``, ``]``, ``{``, ``}``, ``<``, ``>``, ``|``, ``%``,
# ``\`` and every control character — is replaced, so a hostile name can never
# close a label, start a directive or add an edge. See :func:`escape_mermaid_label`.
_LABEL_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:/+-_()"
)

#: ``{`` and ``}`` are Mermaid shape syntax, so a path parameter is rewritten to
#: parentheses instead of being blanked out. ``(repository_id)`` still reads as a
#: parameter to a human while carrying no Mermaid meaning.
_LABEL_SUBSTITUTIONS = {"{": "(", "}": ")"}


class ArchitectureScanError(ValueError):
    """Raised when a scan request is not answerable as asked."""


# ---------------------------------------------------------------------------
# structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonModule:
    """One parsed Python file."""

    path: str
    module: str
    unit: str
    classes: int = 0
    functions: int = 0
    imports: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "module": self.module,
            "unit": self.unit,
            "classes": self.classes,
            "functions": self.functions,
            "imports": list(self.imports),
        }


@dataclass(frozen=True)
class RouterDefinition:
    """An ``APIRouter`` assignment found in a module."""

    module: str
    path: str
    variable: str
    prefix: str = ""
    tags: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.module}.{self.variable}"

    def to_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "path": self.path,
            "variable": self.variable,
            "prefix": self.prefix,
            "tags": list(self.tags),
            "mounts": list(self.mounts),
        }


@dataclass(frozen=True)
class RouteEndpoint:
    """One HTTP endpoint declared by a router decorator."""

    method: str
    path: str
    handler: str
    module: str
    router: str
    mounted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "path": self.path,
            "handler": self.handler,
            "module": self.module,
            "router": self.router,
            "mounted": self.mounted,
        }


@dataclass(frozen=True)
class TableDefinition:
    """A SQLite table name read from a literal ``CREATE TABLE`` statement."""

    name: str
    path: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path}


@dataclass(frozen=True)
class SkippedFile:
    """A file the scan deliberately did not analyse, and why."""

    path: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class PackageUnit:
    """A top-level Python unit that holds at least one scanned module."""

    name: str
    #: "package" (has ``__init__.py``), "module" (a root ``*.py``) or
    #: "directory" (a plain directory, grouped but not importable by name).
    kind: str
    modules: int = 0
    routers: int = 0
    routes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "modules": self.modules,
            "routers": self.routers,
            "routes": self.routes,
        }


@dataclass(frozen=True)
class ArchitectureMap:
    """The deterministic result of one scan.

    ``label`` is a display name only. The absolute filesystem path that was
    scanned is never carried in the result, so it cannot leak to an API caller.
    """

    label: str
    units: tuple[PackageUnit, ...] = ()
    modules: tuple[PythonModule, ...] = ()
    routers: tuple[RouterDefinition, ...] = ()
    routes: tuple[RouteEndpoint, ...] = ()
    tables: tuple[TableDefinition, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()
    skipped: tuple[SkippedFile, ...] = ()
    files_scanned: int = 0
    bytes_read: int = 0
    truncated: bool = False
    notes: tuple[str, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        return {
            "units": len(self.units),
            "modules": len(self.modules),
            "routers": len(self.routers),
            "routes": len(self.routes),
            "tables": len(self.tables),
            "import_edges": len(self.edges),
            "files_scanned": self.files_scanned,
            "skipped": len(self.skipped),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "counts": self.counts,
            "units": [item.to_dict() for item in self.units],
            "modules": [item.to_dict() for item in self.modules],
            "routers": [item.to_dict() for item in self.routers],
            "routes": [item.to_dict() for item in self.routes],
            "tables": [item.to_dict() for item in self.tables],
            "import_edges": [list(edge) for edge in self.edges],
            "skipped": [item.to_dict() for item in self.skipped],
            "bytes_read": self.bytes_read,
            "truncated": self.truncated,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ArchitectureDocument:
    """A finished map: structure, both diagrams, Markdown and sanitized HTML."""

    architecture: ArchitectureMap
    package_diagram: str
    route_diagram: str
    markdown: str
    html: str
    source_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "architecture": self.architecture.to_dict(),
            "package_diagram": self.package_diagram,
            "route_diagram": self.route_diagram,
            "markdown": self.markdown,
            "html": self.html,
            "source_sha256": self.source_sha256,
        }


# ---------------------------------------------------------------------------
# Mermaid safety
# ---------------------------------------------------------------------------


def escape_mermaid_label(value: object, *, limit: int = MAX_LABEL_CHARACTERS) -> str:
    """Make untrusted text safe inside a **quoted** Mermaid node label.

    ``escape_cell`` from :mod:`amoscloud_ai.hub.report` is not sufficient here:
    it targets Markdown tables and leaves ``"``, ``#``, ``;``, ``{`` and ``}``
    untouched, every one of which changes the meaning of a Mermaid statement.

    This function is an **allowlist**, not a blocklist. Only the characters in
    :data:`_LABEL_ALLOWED` survive; anything else becomes ``_``. Consequently a
    label can never contain the double quote that would close it, the ``#`` that
    starts an entity, the ``;``/newline that ends a statement, the ``%%`` that
    starts a directive or comment, or the brackets and arrows that would declare
    another node or edge. Path parameters are rewritten ``{x}`` → ``(x)`` by
    :data:`_LABEL_SUBSTITUTIONS` so they stay readable.

    The result is always non-empty and is always used inside double quotes.
    """

    text = "" if value is None else str(value)
    text = _CONTROL_CHARACTERS.sub(" ", text)
    for source, replacement in _LABEL_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    text = "".join(character if character in _LABEL_ALLOWED else "_" for character in text)
    text = " ".join(text.split())
    safe_limit = max(8, int(limit))
    if len(text) > safe_limit:
        text = f"{text[: safe_limit - 3].rstrip()}..."
    return text or "(unnamed)"


class MermaidGraph:
    """Builder for a flowchart whose node identifiers are generated, not copied.

    Every identifier is ``<prefix>_<slug>`` where ``slug`` is the input reduced
    to ``[A-Za-z0-9_]``, so an identifier can never be a Mermaid keyword such as
    ``end``, can never start with a digit and can never contain syntax. Two
    different names that reduce to the same slug (``a-b`` and ``a_b``) are kept
    distinct by a numeric suffix, so hostile naming cannot merge two nodes into
    one or silently redirect an edge.
    """

    def __init__(self, direction: str = "LR") -> None:
        self.direction = "LR" if direction not in {"LR", "TD", "RL", "BT"} else direction
        self._identifiers: dict[str, str] = {}
        self._used: set[str] = set()
        self._nodes: list[str] = []
        self._declared: set[str] = set()
        self._edges: list[str] = []
        self._edge_keys: set[tuple[str, str]] = set()
        self.trimmed = False

    def identifier(self, prefix: str, value: str) -> str:
        """Return the stable generated identifier for ``value``."""

        key = f"{prefix}\x00{value}"
        existing = self._identifiers.get(key)
        if existing:
            return existing
        safe_prefix = _NON_IDENTIFIER.sub("", prefix) or "n"
        slug = _NON_IDENTIFIER.sub("_", str(value)).strip("_")[:40]
        candidate = f"{safe_prefix}_{slug}" if slug else safe_prefix
        suffix = 2
        while candidate in self._used:
            candidate = f"{safe_prefix}_{slug}_{suffix}" if slug else f"{safe_prefix}_{suffix}"
            suffix += 1
        self._used.add(candidate)
        self._identifiers[key] = candidate
        return candidate

    def node(self, prefix: str, value: str, label: str | None = None) -> str | None:
        """Declare a node, or return ``None`` once the node cap is reached."""

        key = f"{prefix}\x00{value}"
        existing = self._identifiers.get(key)
        if existing and existing in self._declared:
            return existing
        if len(self._declared) >= MAX_DIAGRAM_NODES:
            self.trimmed = True
            return None
        identifier = self.identifier(prefix, value)
        self._declared.add(identifier)
        text = escape_mermaid_label(label if label is not None else value)
        self._nodes.append(f'    {identifier}["{text}"]')
        return identifier

    def edge(self, source: str | None, target: str | None) -> None:
        """Declare an edge between two already-declared nodes."""

        if not source or not target or source == target:
            return
        if (source, target) in self._edge_keys:
            return
        if len(self._edges) >= MAX_DIAGRAM_EDGES:
            self.trimmed = True
            return
        self._edge_keys.add((source, target))
        self._edges.append(f"    {source} --> {target}")

    def render(self) -> str:
        lines = [f"graph {self.direction}"]
        lines.extend(self._nodes)
        lines.extend(self._edges)
        if len(lines) == 1:
            identifier = self.identifier("n", "empty")
            lines.append(f'    {identifier}["No Python structure was detected"]')
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------


def _relative_posix(root: Path, candidate: Path) -> str:
    return PurePosixPath(candidate.relative_to(root).as_posix()).as_posix()


def _module_name(relative: str) -> str:
    parts = list(PurePosixPath(relative).parts)
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(part for part in parts if part)


def _unit_of(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    if len(parts) > 1:
        return parts[0]
    return _module_name(relative)


#: Unit kinds that Python can actually import by top-level name. A plain
#: directory without ``__init__.py`` groups files in the report but is never
#: treated as an import target, which keeps invented edges out of the diagram.
IMPORTABLE_KINDS = frozenset({"package", "module"})


def _discover_units(root: Path) -> dict[str, str]:
    """Classify every top-level name as ``package``, ``module`` or ``directory``.

    A *package* is a first-level directory holding ``__init__.py``; a *module* is
    a first-level ``*.py`` file; a *directory* is any other first-level
    directory. When a package and a same-named root module both exist — this
    repository really does contain both ``Amosclaud/`` and ``Amosclaud.py`` —
    the directory entry is kept, matching Python's own precedence.
    """

    units: dict[str, str] = {}
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return units
    for entry in entries:
        name = entry.name
        if name.startswith(".") or name in SKIP_DIRECTORIES:
            continue
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                kind = "package" if (entry / "__init__.py").is_file() else "directory"
                units.setdefault(name, kind)
            elif entry.is_file() and name.endswith(".py"):
                units.setdefault(_module_name(name), "module")
        except OSError:
            continue
    return units


def _iter_python_files(root: Path) -> tuple[list[Path], list[SkippedFile]]:
    """Collect candidate ``*.py`` paths, refusing anything outside ``root``.

    Symlinks are never followed. A path that resolves outside ``root`` — the
    classic symlink escape — is recorded as skipped rather than read.
    """

    found: list[Path] = []
    skipped: list[SkippedFile] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in SKIP_DIRECTORIES and not name.startswith(".")
        )
        current = Path(directory)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            candidate = current / name
            try:
                resolved = candidate.resolve()
                inside = resolved.is_relative_to(root)
            except (OSError, RuntimeError):
                inside = False
                resolved = candidate
            if not inside:
                try:
                    label = _relative_posix(root, candidate)
                except ValueError:  # pragma: no cover - defensive
                    label = candidate.name
                skipped.append(
                    SkippedFile(path=label, reason="resolves outside the repository root")
                )
                continue
            found.append(candidate)
    return found, skipped


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_strings(node: ast.AST | None) -> tuple[str, ...]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return tuple(
            value
            for value in (_literal_string(element) for element in node.elts)
            if value is not None
        )
    return ()


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _is_api_router(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "APIRouter"
    if isinstance(func, ast.Attribute):
        return func.attr == "APIRouter"
    return False


def _join_path(*parts: str) -> str:
    """Join a mount prefix, a router prefix and a route path into one URL path."""

    pieces: list[str] = []
    trailing = False
    for part in parts:
        piece = (part or "").strip()
        if not piece or piece == "/":
            continue
        trailing = piece.endswith("/")
        pieces.append(f"/{piece.strip('/')}")
    if not pieces:
        return "/"
    joined = "".join(pieces)
    return f"{joined}/" if trailing and not joined.endswith("/") else joined


@dataclass
class _ModuleAnalysis:
    """Mutable per-file findings, collapsed into frozen records afterwards."""

    module: str
    path: str
    unit: str
    classes: int = 0
    functions: int = 0
    imports: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    routers: dict[str, RouterDefinition] = field(default_factory=dict)
    routes: list[tuple[str, str, str, str]] = field(default_factory=list)
    mounts: list[tuple[str, str, str]] = field(default_factory=list)


def _analyse_module(tree: ast.Module, *, module: str, path: str, unit: str) -> _ModuleAnalysis:
    """Read one parsed module. Pure AST inspection; nothing is imported."""

    analysis = _ModuleAnalysis(module=module, path=path, unit=unit)
    router_variables: dict[str, RouterDefinition] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            analysis.classes += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            analysis.functions += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                analysis.imports.add(alias.name.split(".", 1)[0])
                analysis.aliases[(alias.asname or alias.name).split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # A relative import can only target the module's own top-level
                # unit, so it never produces a cross-unit edge.
                analysis.imports.add(unit)
                continue
            base = node.module or ""
            if base:
                analysis.imports.add(base.split(".", 1)[0])
            for alias in node.names:
                local = alias.asname or alias.name
                analysis.aliases[local] = f"{base}.{alias.name}" if base else alias.name
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if not _is_api_router(node.value):
                continue
            prefix = _literal_string(_keyword(node.value, "prefix")) or ""
            tags = _literal_strings(_keyword(node.value, "tags"))
            for target in node.targets:
                if isinstance(target, ast.Name):
                    router_variables[target.id] = RouterDefinition(
                        module=module,
                        path=path,
                        variable=target.id,
                        prefix=prefix,
                        tags=tags,
                    )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "include_router" or not node.args:
                continue
            target = _dotted_name(node.args[0])
            if not target:
                continue
            mount_prefix = _literal_string(_keyword(node, "prefix")) or ""
            analysis.mounts.append((module, target, mount_prefix))

    analysis.routers = router_variables

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
                continue
            method = func.attr.lower()
            if method not in _HTTP_METHODS or func.value.id not in router_variables:
                continue
            route_path = _literal_string(decorator.args[0]) if decorator.args else None
            if route_path is None:
                continue
            analysis.routes.append((func.value.id, method.upper(), route_path, node.name))
    return analysis


def _resolve_mount(target: str, analysis: _ModuleAnalysis) -> tuple[str, str]:
    """Resolve an ``include_router`` argument to a ``(module, variable)`` key.

    Only import aliases collected from the mounting module are consulted, so
    resolution is local and deterministic. An argument that cannot be resolved
    still yields a key; it simply matches no known router and is ignored.
    """

    parts = [part for part in target.split(".") if part]
    if not parts:
        return analysis.module, ""
    if len(parts) == 1:
        alias = analysis.aliases.get(parts[0], "")
        if "." in alias:
            module, _, variable = alias.rpartition(".")
            return module, variable
        return analysis.module, parts[0]
    base, *rest = parts
    variable = rest[-1]
    middle = rest[:-1]
    resolved_base = analysis.aliases.get(base, base)
    return ".".join([resolved_base, *middle]), variable


def scan_architecture(root: Path | str, *, label: str | None = None) -> ArchitectureMap:
    """Statically analyse the Python structure of the tree at ``root``.

    ``root`` is resolved before use and every candidate file is confirmed to
    resolve inside it, so a symlink pointing out of the repository is reported
    as skipped instead of read. Nothing in the tree is imported or executed.
    """

    try:
        resolved_root = Path(root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArchitectureScanError("the repository directory could not be read") from exc
    if not resolved_root.is_dir():
        raise ArchitectureScanError("the repository path is not a directory")

    display = (label or resolved_root.name or "repository").strip() or "repository"
    units = _discover_units(resolved_root)
    candidates, skipped = _iter_python_files(resolved_root)

    analyses: list[_ModuleAnalysis] = []
    modules: list[PythonModule] = []
    tables: dict[str, str] = {}
    files_scanned = 0
    bytes_read = 0
    truncated = False

    for candidate in candidates:
        if files_scanned >= MAX_FILES or bytes_read >= MAX_TOTAL_BYTES:
            truncated = True
            break
        relative = _relative_posix(resolved_root, candidate)
        try:
            size = candidate.stat().st_size
        except OSError:
            skipped.append(SkippedFile(path=relative, reason="the file could not be read"))
            continue
        if size > MAX_FILE_BYTES:
            skipped.append(
                SkippedFile(path=relative, reason=f"larger than the {MAX_FILE_BYTES} byte limit")
            )
            continue
        if bytes_read + size > MAX_TOTAL_BYTES:
            truncated = True
            break
        try:
            raw = candidate.read_bytes()
        except OSError:
            skipped.append(SkippedFile(path=relative, reason="the file could not be read"))
            continue
        files_scanned += 1
        bytes_read += len(raw)
        if b"\x00" in raw:
            skipped.append(SkippedFile(path=relative, reason="binary content"))
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(SkippedFile(path=relative, reason="not valid UTF-8 text"))
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            skipped.append(
                SkippedFile(path=relative, reason=f"could not be parsed ({type(exc).__name__})")
            )
            continue
        for match in _CREATE_TABLE.finditer(text):
            tables.setdefault(match.group("name"), relative)
        unit = _unit_of(relative)
        analysis = _analyse_module(
            tree, module=_module_name(relative), path=relative, unit=unit
        )
        analyses.append(analysis)
        modules.append(
            PythonModule(
                path=relative,
                module=analysis.module,
                unit=unit,
                classes=analysis.classes,
                functions=analysis.functions,
                imports=tuple(
                    sorted(
                        name
                        for name in analysis.imports
                        if units.get(name) in IMPORTABLE_KINDS
                    )
                ),
            )
        )

    routers: dict[tuple[str, str], RouterDefinition] = {}
    for analysis in analyses:
        for variable, definition in analysis.routers.items():
            routers[(analysis.module, variable)] = definition

    mounts: dict[tuple[str, str], list[str]] = {}
    for analysis in analyses:
        for _module, target, prefix in analysis.mounts:
            key = _resolve_mount(target, analysis)
            if key in routers and prefix not in mounts.setdefault(key, []):
                mounts[key].append(prefix)

    routes: list[RouteEndpoint] = []
    for analysis in analyses:
        for variable, method, route_path, handler in analysis.routes:
            definition = analysis.routers.get(variable)
            if definition is None:  # pragma: no cover - defensive
                continue
            attached = mounts.get((analysis.module, variable), [])
            for mount_prefix in attached or [None]:
                routes.append(
                    RouteEndpoint(
                        method=method,
                        path=_join_path(mount_prefix or "", definition.prefix, route_path),
                        handler=handler,
                        module=analysis.module,
                        router=variable,
                        mounted=mount_prefix is not None,
                    )
                )

    route_totals: dict[tuple[str, str], int] = {}
    for analysis in analyses:
        for variable, _method, _path, _handler in analysis.routes:
            key = (analysis.module, variable)
            route_totals[key] = route_totals.get(key, 0) + 1

    router_records = tuple(
        sorted(
            (
                RouterDefinition(
                    module=definition.module,
                    path=definition.path,
                    variable=definition.variable,
                    prefix=definition.prefix,
                    tags=definition.tags,
                    mounts=tuple(mounts.get(key, ())),
                )
                for key, definition in routers.items()
            ),
            key=lambda item: (item.module, item.variable),
        )
    )

    unit_modules: dict[str, int] = {}
    for module in modules:
        unit_modules[module.unit] = unit_modules.get(module.unit, 0) + 1
    unit_routers: dict[str, int] = {}
    unit_routes: dict[str, int] = {}
    for record in router_records:
        unit = record.module.split(".", 1)[0]
        unit_routers[unit] = unit_routers.get(unit, 0) + 1
        unit_routes[unit] = unit_routes.get(unit, 0) + route_totals.get(
            (record.module, record.variable), 0
        )

    unit_records = tuple(
        sorted(
            (
                PackageUnit(
                    name=name,
                    kind=units.get(name, "directory"),
                    modules=unit_modules.get(name, 0),
                    routers=unit_routers.get(name, 0),
                    routes=unit_routes.get(name, 0),
                )
                # Only units that actually hold scanned Python are reported; a
                # top-level directory of assets is not architecture.
                for name in sorted(set(unit_modules) | set(units))
                if unit_modules.get(name, 0)
            ),
            key=lambda item: (-item.modules, item.name),
        )
    )

    known_units = {item.name for item in unit_records}
    edges: set[tuple[str, str]] = set()
    for module in modules:
        for imported in module.imports:
            if imported in known_units and imported != module.unit:
                edges.add((module.unit, imported))
    unmounted = sum(1 for route in routes if not route.mounted)

    notes: list[str] = []
    if truncated:
        notes.append(
            f"The scan stopped at its limits ({MAX_FILES} files or "
            f"{MAX_TOTAL_BYTES} bytes); part of the tree was not analysed."
        )
    if skipped:
        notes.append(f"{len(skipped)} file(s) were skipped and are listed below.")
    if unmounted:
        notes.append(
            f"{unmounted} route(s) belong to a router with no literal "
            "include_router mount, so the path shown for them carries no mount "
            "prefix. A router whose routes are copied onto another router at "
            "runtime is not followed by static analysis."
        )
    notes.append(
        "Only literal values are read: a router prefix, route path or table name "
        "built at runtime is not resolved."
    )

    return ArchitectureMap(
        label=display,
        units=unit_records,
        modules=tuple(sorted(modules, key=lambda item: item.path)),
        routers=router_records,
        routes=tuple(
            sorted(routes, key=lambda item: (item.path, item.method, item.module, item.handler))
        ),
        tables=tuple(
            TableDefinition(name=name, path=tables[name]) for name in sorted(tables)
        ),
        edges=tuple(sorted(edges)),
        skipped=tuple(sorted(skipped, key=lambda item: item.path)),
        files_scanned=files_scanned,
        bytes_read=bytes_read,
        truncated=truncated,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# diagrams
# ---------------------------------------------------------------------------


def build_package_diagram(architecture: ArchitectureMap) -> str:
    """Draw top-level Python units and the import edges between them."""

    graph = MermaidGraph("LR")
    identifiers: dict[str, str] = {}
    for unit in architecture.units:
        suffix = ".py" if unit.kind == "module" else ""
        detail = f"{unit.modules} module(s)" if unit.modules else "no modules scanned"
        if unit.routes:
            detail = f"{detail}, {unit.routes} route(s)"
        identifier = graph.node("u", unit.name, f"{unit.name}{suffix} - {detail}")
        if identifier:
            identifiers[unit.name] = identifier
    for source, target in architecture.edges:
        graph.edge(identifiers.get(source), identifiers.get(target))
    return graph.render()


def build_route_diagram(architecture: ArchitectureMap) -> str:
    """Draw each mount point and the routers attached to it."""

    graph = MermaidGraph("LR")
    counts: dict[tuple[str, str], int] = {}
    for route in architecture.routes:
        key = (route.module, route.router)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(
        architecture.routers,
        key=lambda item: (
            -counts.get((item.module, item.variable), 0),
            item.module,
            item.variable,
        ),
    )
    for record in ordered:
        total = counts.get((record.module, record.variable), 0)
        if not total:
            continue
        leaf = record.module.rsplit(".", 1)[-1] or record.module
        prefix = record.prefix or "/"
        label = f"{leaf}.{record.variable} {prefix} - {total} route(s)"
        router_id = graph.node("r", record.qualified_name, label)
        if not router_id:
            continue
        for mount in record.mounts or ("(not mounted)",):
            mount_label = mount or "/ (no prefix)"
            mount_id = graph.node("m", mount_label, f"mount {mount_label}")
            graph.edge(mount_id, router_id)
    return graph.render()


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join('---' for _ in header)} |",
    ]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return lines


def _diagram_block(title: str, diagram: str) -> list[str]:
    return ["", f"## {title}", "", "```mermaid", diagram, "```"]


def render_architecture_markdown(
    architecture: ArchitectureMap,
    *,
    package_diagram: str | None = None,
    route_diagram: str | None = None,
) -> str:
    """Compose the architecture map as Markdown. Fully deterministic."""

    packages = package_diagram if package_diagram is not None else build_package_diagram(
        architecture
    )
    routes_diagram = route_diagram if route_diagram is not None else build_route_diagram(
        architecture
    )
    counts = architecture.counts
    lines: list[str] = [
        f"# Architecture Map — {escape_cell(architecture.label, limit=120)}",
        "",
        f"**Python files scanned:** {architecture.files_scanned}  ",
        f"**Bytes read:** {architecture.bytes_read}  ",
        "",
        "## Structure",
        "",
    ]
    lines.extend(
        _table(
            ["Measure", "Count"],
            [
                ["Top-level units", str(counts["units"])],
                ["Python modules", str(counts["modules"])],
                ["Import edges between units", str(counts["import_edges"])],
                ["FastAPI routers", str(counts["routers"])],
                ["HTTP routes", str(counts["routes"])],
                ["SQLite tables", str(counts["tables"])],
                ["Files skipped", str(counts["skipped"])],
            ],
        )
    )
    lines.extend(_diagram_block("Package graph", packages))
    lines.extend(_diagram_block("Route surface", routes_diagram))

    lines.extend(["", "## Top-level units", ""])
    if architecture.units:
        lines.extend(
            _table(
                ["Unit", "Kind", "Modules", "Routers", "Routes"],
                [
                    [
                        escape_cell(unit.name, limit=80),
                        escape_cell(unit.kind, limit=20),
                        str(unit.modules),
                        str(unit.routers),
                        str(unit.routes),
                    ]
                    for unit in architecture.units
                ],
            )
        )
    else:
        lines.append("No importable Python units were detected.")

    lines.extend(["", "## HTTP routes", ""])
    if architecture.routes:
        shown = architecture.routes[:MAX_ROUTE_ROWS]
        lines.extend(
            _table(
                ["Method", "Path", "Handler", "Module"],
                [
                    [
                        escape_cell(route.method, limit=10),
                        escape_cell(route.path, limit=160),
                        escape_cell(route.handler, limit=80),
                        escape_cell(route.module, limit=120),
                    ]
                    for route in shown
                ],
            )
        )
        if len(architecture.routes) > len(shown):
            lines.extend(
                [
                    "",
                    f"> {len(architecture.routes) - len(shown)} further route(s) are not "
                    "listed here.",
                ]
            )
    else:
        lines.append("No FastAPI routes were detected.")

    lines.extend(["", "## SQLite tables", ""])
    if architecture.tables:
        shown_tables = architecture.tables[:MAX_TABLE_ROWS]
        lines.extend(
            _table(
                ["Table", "First seen in"],
                [
                    [escape_cell(item.name, limit=80), escape_cell(item.path, limit=160)]
                    for item in shown_tables
                ],
            )
        )
        if len(architecture.tables) > len(shown_tables):
            lines.extend(
                [
                    "",
                    f"> {len(architecture.tables) - len(shown_tables)} further table(s) are "
                    "not listed here.",
                ]
            )
    else:
        lines.append("No literal CREATE TABLE statement was found.")

    if architecture.skipped:
        lines.extend(["", "## Skipped files", ""])
        shown_skipped = architecture.skipped[:MAX_SKIPPED_ROWS]
        lines.extend(
            _table(
                ["Path", "Reason"],
                [
                    [escape_cell(item.path, limit=160), escape_cell(item.reason, limit=120)]
                    for item in shown_skipped
                ],
            )
        )
        if len(architecture.skipped) > len(shown_skipped):
            lines.extend(
                [
                    "",
                    f"> {len(architecture.skipped) - len(shown_skipped)} further skipped "
                    "file(s) are not listed here.",
                ]
            )

    if architecture.notes:
        lines.append("")
        lines.extend(f"> {escape_cell(note, limit=300)}" for note in architecture.notes)

    lines.extend(
        [
            "",
            "---",
            "",
            (
                "*Compiled by the Amosclaud Hub Compiler from static analysis of the "
                "repository working tree. No code was imported or executed and no model "
                "was used; every figure above is counted from parsed source.*"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def build_architecture_document(
    *,
    root: Path | str,
    repository_id: int,
    label: str | None = None,
) -> ArchitectureDocument:
    """Scan, draw and render one architecture map."""

    architecture = scan_architecture(root, label=label)
    package_diagram = build_package_diagram(architecture)
    route_diagram = build_route_diagram(architecture)
    markdown = render_architecture_markdown(
        architecture,
        package_diagram=package_diagram,
        route_diagram=route_diagram,
    )
    document: MarkdownDocument = render_markdown_document(
        markdown,
        repository_id=repository_id,
        branch="main",
        source_path="hub/architecture.md",
    )
    return ArchitectureDocument(
        architecture=architecture,
        package_diagram=package_diagram,
        route_diagram=route_diagram,
        markdown=markdown,
        html=document.html,
        source_sha256=document.source_sha256,
    )
