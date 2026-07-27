"""Contract tests for the Hub Compiler visual architecture mapper.

Covers the static-analysis guarantees (nothing is imported or executed, an
unparseable file is skipped rather than fatal), the scan bounds, the path
traversal refusal, the FastAPI route/router/mount detection, the SQLite table
detection, the Mermaid escaping rules, the structural well-formedness of the
generated diagrams, and the authorization of the read-only HTTP route. No test
performs a network call, and by design no test needs a model runtime — the
mapper never calls one.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.hub import architecture as hub_architecture
from amoscloud_ai.main import create_app

# A node declaration: ``    identifier["label"]``. The label may not contain a
# double quote, which is exactly the property the escaping must guarantee.
NODE_LINE = re.compile(r'^ {4}(?P<id>[A-Za-z][A-Za-z0-9_]*)\["(?P<label>[^"\n]*)"\]$')
EDGE_LINE = re.compile(
    r"^ {4}(?P<source>[A-Za-z][A-Za-z0-9_]*) --> (?P<target>[A-Za-z][A-Za-z0-9_]*)$"
)


def write(root, relative: str, content: str) -> None:
    """Write one file into the synthetic tree under test."""

    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def assert_valid_mermaid(diagram: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Assert the diagram is a structurally well-formed Mermaid flowchart.

    There is no Mermaid parser available to the test suite without adding a new
    dependency, so this is a strict structural check rather than a claim that
    the reference implementation accepted the text: the header must be a
    ``graph`` declaration, every remaining line must be either a quoted node
    declaration or an edge between two identifiers, and every edge endpoint must
    have been declared as a node.
    """

    lines = diagram.split("\n")
    assert lines, "a diagram is never empty"
    assert re.fullmatch(r"graph (LR|TD|RL|BT)", lines[0]), lines[0]
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for line in lines[1:]:
        node = NODE_LINE.match(line)
        if node:
            assert node.group("id") not in nodes, f"duplicate node {node.group('id')}"
            nodes.add(node.group("id"))
            continue
        edge = EDGE_LINE.match(line)
        assert edge, f"unrecognised Mermaid line: {line!r}"
        edges.add((edge.group("source"), edge.group("target")))
    for source, target in edges:
        assert source in nodes, f"edge from undeclared node {source}"
        assert target in nodes, f"edge to undeclared node {target}"
    assert "```" not in diagram
    return nodes, edges


@pytest.fixture
def sample_tree(tmp_path):
    """A small but realistic repository: two packages, a router and a table."""

    root = tmp_path / "project"
    write(root, "servicepkg/__init__.py", "")
    write(
        root,
        "servicepkg/api.py",
        (
            "from fastapi import APIRouter\n"
            "from corepkg import store\n"
            "import json\n"
            "\n"
            'router = APIRouter(prefix="/widgets", tags=["widgets"])\n'
            "\n"
            "\n"
            '@router.get("/{widget_id}")\n'
            "def read_widget(widget_id: int) -> dict:\n"
            "    return {}\n"
            "\n"
            "\n"
            '@router.post("/")\n'
            "def create_widget() -> dict:\n"
            "    return {}\n"
        ),
    )
    write(root, "corepkg/__init__.py", "")
    write(
        root,
        "corepkg/store.py",
        (
            "import sqlite3\n"
            "\n"
            "\n"
            "class Store:\n"
            "    def setup(self, db: sqlite3.Connection) -> None:\n"
            '        db.execute("CREATE TABLE IF NOT EXISTS widgets (id INTEGER)")\n'
            '        db.execute("CREATE TABLE audit_log (id INTEGER)")\n'
        ),
    )
    write(
        root,
        "main.py",
        (
            "from fastapi import FastAPI\n"
            "from servicepkg import api\n"
            "\n"
            "app = FastAPI()\n"
            'app.include_router(api.router, prefix="/api/v1")\n'
        ),
    )
    write(root, "assets/logo.txt", "not python\n")
    return root


# ---------------------------------------------------------------------------
# structure detection
# ---------------------------------------------------------------------------


def test_packages_modules_and_import_edges_are_detected(sample_tree):
    architecture = hub_architecture.scan_architecture(sample_tree, label="project")

    assert architecture.label == "project"
    kinds = {unit.name: unit.kind for unit in architecture.units}
    assert kinds["servicepkg"] == "package"
    assert kinds["corepkg"] == "package"
    assert kinds["main"] == "module"
    assert architecture.counts["modules"] == 5
    assert ("servicepkg", "corepkg") in architecture.edges
    # ``json`` and ``fastapi`` are external and must never become nodes.
    assert not any(target in {"json", "fastapi"} for _source, target in architecture.edges)
    assert architecture.truncated is False
    assert architecture.skipped == ()


def test_relative_imports_never_create_a_cross_unit_edge(tmp_path):
    root = tmp_path / "project"
    write(root, "pkg/__init__.py", "")
    write(root, "pkg/one.py", "from . import two\nfrom .two import thing\n")
    write(root, "pkg/two.py", "thing = 1\n")

    architecture = hub_architecture.scan_architecture(root)

    assert architecture.edges == ()


def test_router_prefix_mount_and_methods_compose_the_full_path(sample_tree):
    architecture = hub_architecture.scan_architecture(sample_tree)

    by_handler = {route.handler: route for route in architecture.routes}
    assert by_handler["read_widget"].method == "GET"
    assert by_handler["read_widget"].path == "/api/v1/widgets/{widget_id}"
    assert by_handler["read_widget"].mounted is True
    assert by_handler["create_widget"].method == "POST"
    assert by_handler["create_widget"].path == "/api/v1/widgets"
    definition = architecture.routers[0]
    assert definition.prefix == "/widgets"
    assert definition.tags == ("widgets",)
    assert definition.mounts == ("/api/v1",)


def test_an_unmounted_router_is_reported_as_unmounted(tmp_path):
    root = tmp_path / "project"
    write(root, "pkg/__init__.py", "")
    write(
        root,
        "pkg/api.py",
        (
            "from fastapi import APIRouter\n"
            'router = APIRouter(prefix="/orphan")\n'
            "\n"
            "\n"
            '@router.delete("/{item}")\n'
            "def drop(item: str) -> None:\n"
            "    return None\n"
        ),
    )

    architecture = hub_architecture.scan_architecture(root)

    assert len(architecture.routes) == 1
    route = architecture.routes[0]
    assert route.mounted is False
    assert route.path == "/orphan/{item}"
    assert any("no literal" in note for note in architecture.notes)


def test_a_router_mounted_twice_is_reported_once_per_mount(tmp_path):
    root = tmp_path / "project"
    write(root, "pkg/__init__.py", "")
    write(
        root,
        "pkg/api.py",
        (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "\n"
            "\n"
            '@router.get("/ping")\n'
            "def ping() -> dict:\n"
            "    return {}\n"
        ),
    )
    write(
        root,
        "main.py",
        (
            "from pkg.api import router as ping_router\n"
            "app = object()\n"
            'app.include_router(ping_router, prefix="/api/v1")\n'
            "app.include_router(ping_router)\n"
        ),
    )

    architecture = hub_architecture.scan_architecture(root)

    assert sorted(route.path for route in architecture.routes) == ["/api/v1/ping", "/ping"]


def test_non_literal_route_values_are_not_guessed(tmp_path):
    root = tmp_path / "project"
    write(root, "pkg/__init__.py", "")
    write(
        root,
        "pkg/api.py",
        (
            "from fastapi import APIRouter\n"
            "PREFIX = '/computed'\n"
            "router = APIRouter(prefix=PREFIX)\n"
            "\n"
            "\n"
            "@router.get(PREFIX + '/thing')\n"
            "def thing() -> dict:\n"
            "    return {}\n"
            "\n"
            "\n"
            "@router.get('/literal')\n"
            "def literal() -> dict:\n"
            "    return {}\n"
        ),
    )

    architecture = hub_architecture.scan_architecture(root)

    assert [route.path for route in architecture.routes] == ["/literal"]
    assert architecture.routers[0].prefix == ""


def test_create_table_names_are_read_and_dynamic_names_are_not_invented(sample_tree):
    write(
        sample_tree,
        "corepkg/dynamic.py",
        (
            "TABLE = 'chosen'\n"
            "\n"
            "\n"
            "def setup(db):\n"
            '    db.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (id INTEGER)")\n'
        ),
    )

    architecture = hub_architecture.scan_architecture(sample_tree)

    names = [table.name for table in architecture.tables]
    assert names == ["audit_log", "widgets"]
    # The f-string placeholder must not be reported as a table called "IF".
    assert "IF" not in names


# ---------------------------------------------------------------------------
# safety: static only, bounded, and confined to the repository
# ---------------------------------------------------------------------------


def test_an_unparseable_file_is_skipped_and_reported_not_fatal(sample_tree):
    write(sample_tree, "servicepkg/broken.py", "def oops(:\n")

    architecture = hub_architecture.scan_architecture(sample_tree)

    skipped = {item.path: item.reason for item in architecture.skipped}
    assert "servicepkg/broken.py" in skipped
    assert "SyntaxError" in skipped["servicepkg/broken.py"]
    # The rest of the scan still succeeded.
    assert architecture.counts["routes"] == 2


def test_scanned_code_is_never_imported_or_executed(sample_tree, tmp_path):
    marker = tmp_path / "executed.txt"
    write(
        sample_tree,
        "servicepkg/hostile.py",
        (
            "import pathlib\n"
            f"pathlib.Path({str(marker)!r}).write_text('executed')\n"
            "raise SystemExit('import side effect')\n"
        ),
    )

    architecture = hub_architecture.scan_architecture(sample_tree)

    assert marker.exists() is False
    assert any(module.path == "servicepkg/hostile.py" for module in architecture.modules)


def test_binary_and_oversized_files_are_skipped(sample_tree, monkeypatch):
    (sample_tree / "servicepkg" / "blob.py").write_bytes(b"\x00\x01\x02binary")
    write(sample_tree, "servicepkg/huge.py", "x = 1\n" * 200)
    monkeypatch.setattr(hub_architecture, "MAX_FILE_BYTES", 100)

    architecture = hub_architecture.scan_architecture(sample_tree)

    reasons = {item.path: item.reason for item in architecture.skipped}
    assert reasons["servicepkg/blob.py"] == "binary content"
    assert "byte limit" in reasons["servicepkg/huge.py"]


def test_vendor_and_build_directories_are_never_entered(sample_tree):
    write(sample_tree, "node_modules/pkg/index.py", "x = 1\n")
    write(sample_tree, "__pycache__/cached.py", "x = 1\n")
    write(sample_tree, ".venv/lib/thing.py", "x = 1\n")
    write(sample_tree, "dist/bundle.py", "x = 1\n")

    architecture = hub_architecture.scan_architecture(sample_tree)

    paths = {module.path for module in architecture.modules}
    assert not any(
        path.startswith(("node_modules/", "__pycache__/", ".venv/", "dist/")) for path in paths
    )


def test_the_file_cap_sets_the_truncated_flag(sample_tree, monkeypatch):
    monkeypatch.setattr(hub_architecture, "MAX_FILES", 2)

    architecture = hub_architecture.scan_architecture(sample_tree)

    assert architecture.files_scanned == 2
    assert architecture.truncated is True
    assert any("stopped at its limits" in note for note in architecture.notes)


def test_the_byte_cap_sets_the_truncated_flag(sample_tree, monkeypatch):
    monkeypatch.setattr(hub_architecture, "MAX_TOTAL_BYTES", 30)

    architecture = hub_architecture.scan_architecture(sample_tree)

    assert architecture.truncated is True
    assert architecture.bytes_read <= 30 + hub_architecture.MAX_FILE_BYTES


def test_a_symlink_escaping_the_repository_is_refused(sample_tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.py"
    secret.write_text("PASSWORD = 'leaked'\n", encoding="utf-8")
    (sample_tree / "servicepkg" / "escape.py").symlink_to(secret)

    architecture = hub_architecture.scan_architecture(sample_tree)

    reasons = {item.path: item.reason for item in architecture.skipped}
    assert reasons["servicepkg/escape.py"] == "resolves outside the repository root"
    assert not any(module.path == "servicepkg/escape.py" for module in architecture.modules)


def test_a_symlinked_directory_escaping_the_repository_is_not_followed(sample_tree, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir(exist_ok=True)
    (outside / "hidden.py").write_text("SECRET = 1\n", encoding="utf-8")
    (sample_tree / "linked").symlink_to(outside, target_is_directory=True)

    architecture = hub_architecture.scan_architecture(sample_tree)

    assert not any(module.path.startswith("linked/") for module in architecture.modules)


def test_a_missing_root_is_a_clean_error(tmp_path):
    with pytest.raises(hub_architecture.ArchitectureScanError):
        hub_architecture.scan_architecture(tmp_path / "does-not-exist")
    plain_file = tmp_path / "file.txt"
    plain_file.write_text("x", encoding="utf-8")
    with pytest.raises(hub_architecture.ArchitectureScanError):
        hub_architecture.scan_architecture(plain_file)


def test_an_empty_tree_still_produces_a_valid_document(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    document = hub_architecture.build_architecture_document(
        root=root, repository_id=1, label="empty"
    )

    assert document.architecture.counts["modules"] == 0
    assert_valid_mermaid(document.package_diagram)
    assert_valid_mermaid(document.route_diagram)
    assert "No importable Python units were detected." in document.markdown
    assert "No FastAPI routes were detected." in document.markdown
    assert document.html.strip()


# ---------------------------------------------------------------------------
# Mermaid escaping: the specific hazard of this phase
# ---------------------------------------------------------------------------


def test_escape_mermaid_label_removes_every_syntax_character():
    escaped = hub_architecture.escape_mermaid_label('a"b#c;d[e]f{g}h<i>j|k%%l`m\\n')
    for character in '"#;[]<>|%`\\':
        assert character not in escaped
    assert hub_architecture.escape_mermaid_label("line\nbreak") == "line break"
    assert hub_architecture.escape_mermaid_label("") == "(unnamed)"
    assert hub_architecture.escape_mermaid_label(None) == "(unnamed)"
    assert hub_architecture.escape_mermaid_label("x" * 500).endswith("...")
    assert len(hub_architecture.escape_mermaid_label("x" * 500)) == (
        hub_architecture.MAX_LABEL_CHARACTERS
    )
    # Path parameters stay readable instead of being blanked out.
    assert hub_architecture.escape_mermaid_label("/r/{id}") == "/r/(id)"
    # Ordinary module and route text is untouched.
    assert hub_architecture.escape_mermaid_label("amoscloud_ai.hub - 2 route(s)") == (
        "amoscloud_ai.hub - 2 route(s)"
    )


def test_a_hostile_module_name_cannot_break_out_of_a_node_label(tmp_path):
    """The core injection test: a crafted directory name must stay a label.

    The name below tries to close the label, terminate the statement, declare a
    new node and add an edge to it. If any of that succeeded the diagram would
    gain a node or an edge that the scan never found.
    """

    hostile = 'evil"];zz["pwned"]-->qq["x'
    root = tmp_path / "project"
    write(root, f"{hostile}/__init__.py", "")
    write(root, f"{hostile}/mod.py", "x = 1\n")
    write(root, "clean/__init__.py", "")
    write(root, "clean/mod.py", "x = 1\n")

    architecture = hub_architecture.scan_architecture(root)
    diagram = hub_architecture.build_package_diagram(architecture)

    nodes, edges = assert_valid_mermaid(diagram)
    labels = [match.group("label") for match in map(NODE_LINE.match, diagram.split("\n")) if match]
    # Exactly the two real units, no smuggled third node and no smuggled edge.
    assert len(nodes) == 2
    assert edges == set()
    assert len(labels) == 2
    assert diagram.count('"') == 4  # two quoted labels, nothing more
    assert not any(label.strip() == "pwned" for label in labels)
    assert any(label.startswith("evil") for label in labels)
    # No label carries syntax that Mermaid would act on.
    for label in labels:
        for character in '"[]{}<>;#%|`\\':
            assert character not in label
    assert "-->" not in " ".join(labels)


def test_hostile_route_and_table_text_cannot_reshape_the_route_diagram(tmp_path):
    root = tmp_path / "project"
    write(root, "pkg/__init__.py", "")
    write(
        root,
        "pkg/api.py",
        (
            "from fastapi import APIRouter\n"
            'router = APIRouter(prefix="/a\\"];x-->y;%%{init}%%")\n'
            "\n"
            "\n"
            '@router.get("/b\\"];zz")\n'
            "def handler() -> dict:\n"
            "    return {}\n"
        ),
    )
    write(
        root,
        "main.py",
        ("from pkg import api\n" 'app = object()\napp.include_router(api.router, prefix="/api")\n'),
    )

    architecture = hub_architecture.scan_architecture(root)
    diagram = hub_architecture.build_route_diagram(architecture)

    nodes, edges = assert_valid_mermaid(diagram)
    assert len(nodes) == 2 and len(edges) == 1  # one mount, one router
    labels = [match.group("label") for match in map(NODE_LINE.match, diagram.split("\n")) if match]
    for label in labels:
        for character in '"[]{}<>;#%|`\\':
            assert character not in label
        assert "-->" not in label
    # ``%%{init}%%`` cannot survive as a Mermaid directive.
    assert "%%" not in diagram and "{" not in diagram
    # The raw text is still preserved verbatim in the structured data.
    assert architecture.routes[0].path == '/api/a"];x-->y;%%{init}%%/b"];zz'


def test_names_that_reduce_to_the_same_identifier_stay_distinct_nodes():
    graph = hub_architecture.MermaidGraph()
    first = graph.node("u", "a-b")
    second = graph.node("u", "a_b")

    assert first != second
    assert graph.node("u", "a-b") == first  # stable on repeat
    nodes, _edges = assert_valid_mermaid(graph.render())
    assert nodes == {first, second}


def test_a_mermaid_keyword_can_never_become_a_node_identifier():
    graph = hub_architecture.MermaidGraph()
    for keyword in ("end", "graph", "subgraph", "class", "click", "1"):
        identifier = graph.node("u", keyword)
        assert identifier is not None
        assert identifier not in {"end", "graph", "subgraph", "class", "click"}
        assert identifier[0].isalpha()

    assert_valid_mermaid(graph.render())


def test_the_diagram_node_cap_is_enforced_and_reported():
    graph = hub_architecture.MermaidGraph()
    identifiers = [
        graph.node("u", f"unit-{index}")
        for index in range(hub_architecture.MAX_DIAGRAM_NODES + 5)
    ]

    assert identifiers[-1] is None
    assert graph.trimmed is True
    nodes, _edges = assert_valid_mermaid(graph.render())
    assert len(nodes) == hub_architecture.MAX_DIAGRAM_NODES


def test_generated_diagrams_are_structurally_valid_for_a_real_tree(sample_tree):
    architecture = hub_architecture.scan_architecture(sample_tree)

    package_nodes, package_edges = assert_valid_mermaid(
        hub_architecture.build_package_diagram(architecture)
    )
    route_nodes, route_edges = assert_valid_mermaid(
        hub_architecture.build_route_diagram(architecture)
    )

    assert len(package_nodes) == 3  # servicepkg, corepkg, main
    assert len(package_edges) == 2  # servicepkg -> corepkg, main -> servicepkg
    assert len(route_nodes) == 2 and len(route_edges) == 1


# ---------------------------------------------------------------------------
# Markdown and HTML rendering
# ---------------------------------------------------------------------------


def test_markdown_carries_counts_tables_and_a_mermaid_fence(sample_tree):
    document = hub_architecture.build_architecture_document(
        root=sample_tree, repository_id=1, label="project"
    )

    assert "# Architecture Map — project" in document.markdown
    assert "| Top-level units | 3 |" in document.markdown
    assert "| HTTP routes | 2 |" in document.markdown
    assert "| SQLite tables | 2 |" in document.markdown
    assert document.markdown.count("```mermaid") == 2
    assert document.markdown.count("```") == 4
    # ``escape_cell`` escapes Markdown structure characters, so the path is
    # shown with escaped underscores; braces are not Markdown syntax.
    assert "| GET | /api/v1/widgets/{widget\\_id} |" in document.markdown
    assert "widgets" in document.markdown and "audit\\_log" in document.markdown
    assert "No code was imported or executed and no model was used" in document.markdown
    assert len(document.source_sha256) == 64


def test_html_is_rendered_through_the_markdown_service_and_sanitized(sample_tree):
    write(sample_tree, "<script>alert(1)</script>/__init__.py", "")
    write(sample_tree, "<script>alert(1)</script>/mod.py", "x = 1\n")

    document = hub_architecture.build_architecture_document(
        root=sample_tree, repository_id=1, label="<img src=x onerror=alert(1)>"
    )

    lowered = document.html.lower()
    assert "<script" not in lowered
    assert "<img" not in lowered
    # The hostile text survives only as escaped body text, never as a tag or an
    # attribute. (A real repository name cannot even contain these characters:
    # ``repositories._NAME_RE`` rejects them at creation time.)
    assert "&lt;img src=x onerror=alert(1)&gt;" in document.html
    assert "&lt;script&gt;" in document.html
    assert "<h1" in document.html and "<table>" in document.html
    assert 'class="language-mermaid"' in document.html


def test_the_scan_is_deterministic(sample_tree):
    first = hub_architecture.build_architecture_document(
        root=sample_tree, repository_id=1, label="project"
    )
    second = hub_architecture.build_architecture_document(
        root=sample_tree, repository_id=1, label="project"
    )

    assert first.markdown == second.markdown
    assert first.source_sha256 == second.source_sha256
    assert first.package_diagram == second.package_diagram
    assert first.route_diagram == second.route_diagram


def test_the_mapper_never_touches_the_model_layer(sample_tree, monkeypatch):
    """Phase 2 is model-free by design; inference capacity is the bottleneck."""

    from amoscloud_ai import provider

    def _must_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("the architecture mapper must never call the model layer")

    monkeypatch.setattr(provider, "reply", _must_not_be_called)
    monkeypatch.setattr(provider, "is_configured", _must_not_be_called)

    document = hub_architecture.build_architecture_document(
        root=sample_tree, repository_id=1, label="project"
    )

    assert document.markdown


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


def _create_user_and_session(email: str) -> tuple[str, object]:
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)"
            " VALUES (?,?,?,'password',0,?)",
            (
                email.split("@", 1)[0],
                email,
                auth._hash_password("strong-password"),
                now.isoformat(),
            ),
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                user_id,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return token, user


@pytest.fixture
def hosted_repository(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")
    owner_token, owner = _create_user_and_session("owner@example.com")
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="mapped-project", visibility="public"), owner
    )
    return {"token": owner_token, "repository": repository}


def _get(path: str, token: str | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            if token:
                client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.get(path)

    return asyncio.run(_go())


def test_architecture_requires_authentication(hosted_repository):
    repository_id = hosted_repository["repository"].id

    response = _get(f"/api/v1/hub/repositories/{repository_id}/architecture")

    assert response.status_code == 401


def test_architecture_hides_repositories_the_caller_cannot_see(hosted_repository):
    _, other_owner = _create_user_and_session("other-owner@example.com")
    private_repository = repositories.create_repository(
        repositories.RepositoryCreate(name="private-project", visibility="private"),
        other_owner,
    )

    response = _get(
        f"/api/v1/hub/repositories/{private_repository.id}/architecture",
        token=hosted_repository["token"],
    )

    assert response.status_code == 404


def test_architecture_rejects_an_invalid_repository_id(hosted_repository):
    response = _get(
        "/api/v1/hub/repositories/0/architecture", token=hosted_repository["token"]
    )

    assert response.status_code == 422


def test_architecture_returns_diagrams_markdown_and_html(hosted_repository):
    repository_id = hosted_repository["repository"].id
    root = repositories._repo_path(repository_id)
    write(root, "servicepkg/__init__.py", "")
    write(
        root,
        "servicepkg/api.py",
        (
            "from fastapi import APIRouter\n"
            'router = APIRouter(prefix="/things")\n'
            "\n"
            "\n"
            '@router.get("/list")\n'
            "def list_things() -> dict:\n"
            "    return {}\n"
        ),
    )

    response = _get(
        f"/api/v1/hub/repositories/{repository_id}/architecture",
        token=hosted_repository["token"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == repository_id
    assert body["architecture"]["label"] == "mapped-project"
    assert body["architecture"]["counts"]["routes"] == 1
    assert body["architecture"]["routes"][0]["path"] == "/things/list"
    assert body["branch"] == "main"
    assert len(body["commit"] or "") == 40
    assert_valid_mermaid(body["package_diagram"])
    assert_valid_mermaid(body["route_diagram"])
    assert "Architecture Map" in body["markdown"]
    assert "<h1" in body["html"]
    assert len(body["source_sha256"]) == 64
    # The absolute filesystem path is never exposed to the caller.
    assert str(root) not in response.text
    assert "modules" not in body["architecture"]


def test_architecture_route_is_read_only():
    """Phase 2 must not expose any write surface under /hub."""

    from amoscloud_ai.api.routes import hub_architecture as route_module

    methods = {
        method
        for route in route_module.router.routes
        for method in getattr(route, "methods", set())
    }
    assert methods == {"GET"}


def test_the_architecture_route_is_registered_on_the_application():
    paths = {getattr(route, "path", "") for route in create_app().routes}

    assert "/api/v1/hub/repositories/{repository_id}/architecture" in paths
