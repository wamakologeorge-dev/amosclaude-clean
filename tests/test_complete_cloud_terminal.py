import base64
import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from amoscloud_ai import managed_terminal, workspace_runtime, workspace_terminal
from amoscloud_ai.main import create_app
from src.agent.actions import _resolve_workspace


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_complete_terminal_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert {
        "/api/v1/cloud-workspaces/repositories/{repository_id}/terminal-ticket-v2",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/managed-terminal/{terminal_id}",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/agent-hub",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/agent-hub/messages",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/tools",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/tools/commit",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/tools/pull",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/tools/push",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/tools/sync-push",
    }.issubset(paths)


def test_terminal_v2_ticket_binds_session_profile_and_signature(monkeypatch) -> None:
    token = "runtime-test-token-with-enough-entropy"
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", token)
    monkeypatch.setenv(
        "AMOSCLAUD_WORKSPACE_RUNTIME_URL",
        "https://private-runtime.example",
    )
    monkeypatch.setenv(
        "AMOSCLAUD_WORKSPACE_PUBLIC_URL",
        "https://terminal.amosclaud.com",
    )
    monkeypatch.setattr(workspace_terminal.time, "time", lambda: 1_700_000_000)

    result = workspace_terminal.terminal_ticket(
        {"id": "ws_0123456789abcdef", "repository_id": 7, "owner_id": 3},
        11,
        terminal_id="term_0123456789abcdef",
        profile="bash",
    )

    parsed = urlparse(result["websocket_url"])
    assert parsed.scheme == "wss"
    assert parsed.netloc == "terminal.amosclaud.com"
    assert parsed.path == "/v2/terminal/ws_0123456789abcdef"
    raw_ticket = parse_qs(parsed.query)["ticket"][0]
    raw = base64.urlsafe_b64decode(raw_ticket + "=" * (-len(raw_ticket) % 4))
    ticket = json.loads(raw)

    assert ticket["version"] == 2
    assert ticket["terminal_id"] == "term_0123456789abcdef"
    assert ticket["profile"] == "bash"
    assert ticket["expires_at"] == 1_700_000_120
    payload = (
        "v2:ws_0123456789abcdef:11:1700000120:"
        f"{ticket['nonce']}:term_0123456789abcdef:bash"
    ).encode()
    expected = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, ticket["signature"])


def test_browser_terminal_is_modular_cloud_connected_and_feature_complete() -> None:
    loader = _source("web/cloud-workspace.js")
    main = _source("web/cloud-terminal/main.js")
    session = _source("web/cloud-terminal/session.js")
    hub = _source("web/cloud-terminal/agent-hub.js")
    project_tools = _source("web/cloud-terminal/project-tools.js")
    features = _source("web/cloud-terminal/workspace-features.js")

    assert "/static/cloud-terminal/main.js" in loader
    assert "terminal-ticket-v2" in session
    assert "new WebSocket(ticket.websocket_url)" in session
    assert "ResizeObserver" in session
    assert "runCommand" in session
    assert "interrupt()" in session
    assert "registerOscHandler(777" in session
    assert "amos:finish" in session
    assert "exportTranscript" in session
    assert "findNext" in session and "findPrevious" in session
    assert "Split" in main
    assert "writable repository" in main
    assert "nano and vim" in main
    assert "Running now" in main
    assert "Stop process" in main
    assert "Managed runtime connected" in main
    assert "TerminalAgentHub" in main
    assert "ProjectToolbelt" in main
    assert "WorkspaceFeatureCells" in main
    assert "data-workspace-features" in main
    assert "/agent-hub/messages" in hub
    assert "Attach recent output from the active terminal" in hub
    assert "Authorize verified repository changes" in hub
    assert "Doctor" in hub and "Fixer" in hub
    assert "/tools/commit" in project_tools
    assert "/tools/${action}" in project_tools
    assert "sync-push" in project_tools
    assert "Run app" in project_tools
    assert "Debug" in project_tools
    assert "Edit file" in project_tools
    assert "Run any command" in project_tools
    for label in ("Ports", "Problems", "Connectors", "Network"):
        assert f">{label}<" in features
    assert "ss -ltnp" in features
    assert "git diff --check" in features
    assert "ip -brief address" in features


def test_runtime_supports_persistent_tmux_sessions_and_resize_protocol() -> None:
    source = _source("services/workspace_runtime/terminal_runtime.py")
    dockerfile = _source("services/workspace_runtime/workspace-image/Dockerfile")
    service_dockerfile = _source("services/workspace_runtime/Dockerfile")

    assert '@app.websocket("/v2/terminal/{workspace_id}")' in source
    assert '"tmux",' in source
    assert '"new-session",' in source
    assert '"-A",' in source
    assert "TIOCSWINSZ" in source
    assert 'message_type not in {"resize", "ping", "terminate"}' in source
    assert "kill-session" in source
    assert "tmux" in dockerfile
    assert "bash-completion" in dockerfile
    assert "nano" in dockerfile and "vim-tiny" in dockerfile
    assert "iproute2" in dockerfile and "net-tools" in dockerfile
    assert "dnsutils" in dockerfile and "netcat-openbsd" in dockerfile
    assert "gdb" in dockerfile and "strace" in dockerfile
    assert "/usr/local/bin/amos" in dockerfile
    assert 'CMD ["uvicorn", "terminal_runtime:app"' in service_dockerfile


def test_managed_runtime_is_available_without_external_workspace_service(monkeypatch) -> None:
    monkeypatch.delenv("AMOSCLAUD_WORKSPACE_RUNTIME_URL", raising=False)
    monkeypatch.delenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", raising=False)
    monkeypatch.setenv("AMOSCLAUD_MANAGED_TERMINAL_ENABLED", "true")

    result = managed_terminal.health(external=workspace_runtime.runtime_health())

    assert result["configured"] is True
    assert result["ok"] is True
    assert result["provider"] == "managed"
    assert result["managed_fallback"] is True
    assert "scrubbed environment" in result["security_boundary"]


def test_workspace_table_repairs_legacy_schema_and_duplicates(tmp_path, monkeypatch) -> None:
    database = tmp_path / "auth.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE cloud_workspaces (
                id TEXT PRIMARY KEY,
                repository_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                runtime_status TEXT
            );
            INSERT INTO cloud_workspaces(id,repository_id,owner_id,runtime_status)
            VALUES ('ws_old',7,3,'not_started'),('ws_duplicate',7,3,'running');
            """
        )

    @contextmanager
    def test_db():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    monkeypatch.setattr(workspace_runtime, "_db", test_db)
    workspace_runtime.ensure_workspace_table()
    workspace = workspace_runtime.workspace_for_repository(7, 3)

    with test_db() as db:
        rows = db.execute(
            "SELECT * FROM cloud_workspaces WHERE repository_id=7"
        ).fetchall()
        indexes = db.execute("PRAGMA index_list(cloud_workspaces)").fetchall()
    assert len(rows) == 1
    assert workspace["id"] == "ws_old"
    assert workspace["created_at"]
    assert any(bool(row["unique"]) for row in indexes)


def test_agent_hub_redacts_secrets_handles_help_and_disables_unsafe_escalation() -> None:
    source = _source("amoscloud_ai/api/routes/cloud_workspaces.py")

    assert 'Literal["doctor", "fixer", "autonomous", "underground"]' in source
    assert "_safe_terminal_output" in source
    assert "[redacted]" in source
    assert "_HELP_REQUEST" in source
    assert "_agent_help_response" in source
    assert "Read-only diagnosis: repository write authority is not granted." in source
    assert "Diagnosis only: do not modify repository files." not in source
    assert '"allow_force_push": False' in source
    assert '"allow_protected_branch_write": False' in source
    assert '"require_verification": True' in source
    assert "no force push" in source.lower()
    assert "no protected-branch write" in source.lower()


def test_autonomous_workspace_accepts_persistent_repository_root(tmp_path, monkeypatch) -> None:
    repository_root = tmp_path / "repositories"
    repository = repository_root / "7"
    repository.mkdir(parents=True)
    monkeypatch.setenv("REPOSITORY_STORAGE_PATH", str(repository_root))

    assert _resolve_workspace(str(repository)) == repository.resolve()


def test_project_tools_support_native_and_github_repository_workflows() -> None:
    source = _source("amoscloud_ai/api/routes/terminal_tools.py")

    assert '@router.get("/repositories/{repository_id}/tools")' in source
    assert '@router.post("/repositories/{repository_id}/tools/commit")' in source
    assert '@router.post("/repositories/{repository_id}/tools/pull")' in source
    assert '@router.post("/repositories/{repository_id}/tools/push")' in source
    assert '@router.post("/repositories/{repository_id}/tools/sync-push")' in source
    assert '"source": "github" if github_full_name else "amosclaud"' in source
    assert "push_github_repository" in source
    assert "pull_github_repository" in source
    assert "authenticated_git" in source
    assert "repo.git.fetch" in source
    assert "repo.git.rebase" in source
    assert '"force_push": False' in source
    assert "git status --short --branch" in source
    assert "python -m pytest -q" in source
    assert "npm run" in source


def test_shell_profile_and_amos_command_make_editing_and_debugging_simple() -> None:
    profile = _source("services/workspace_runtime/workspace-image/terminal-profile.sh")
    command = _source("services/workspace_runtime/workspace-image/amos")
    dockerfile = _source("Dockerfile")

    assert "git symbolic-ref --quiet --short HEAD" in profile
    assert "PROMPT_COMMAND='history -a; __amosclaud_prompt'" in profile
    assert "alias gs='git status --short --branch'" in profile
    assert "amos edit <path>" in command
    assert "amos debug" in command
    assert "amos ports" in command
    assert "amos problems" in command
    assert "amos connectors" in command
    assert "amos network" in command
    assert "python3 -m pdb" in command
    assert "NODE_OPTIONS=--inspect" in command
    assert "[Amosclaud Debug] Starting" in command
    assert "exec nano" in command
    assert "exec vim" in command
    assert "git commit -m" in command
    assert "Sync & Push" in command
    assert "AMOSCLAUD_MANAGED_TERMINAL_ENABLED=true" in dockerfile
    assert "COPY services/workspace_runtime/workspace-image/amos" in dockerfile
    assert "gdb" in dockerfile and "strace" in dockerfile
