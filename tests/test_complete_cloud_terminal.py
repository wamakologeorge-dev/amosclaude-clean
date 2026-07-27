import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from amoscloud_ai import workspace_terminal
from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_complete_terminal_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert {
        "/api/v1/cloud-workspaces/repositories/{repository_id}/terminal-ticket-v2",
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
    assert "exportTranscript" in session
    assert "findNext" in session and "findPrevious" in session
    assert "Split" in main
    assert "writable repository" in main
    assert "nano and vim editors" in main
    assert "TerminalAgentHub" in main
    assert "ProjectToolbelt" in main
    assert "WorkspaceFeatureCells" in main
    assert "data-workspace-features" in main
    assert "/agent-hub/messages" in hub
    assert "Attach recent output from the active terminal" in hub
    assert "Authorize verified repository changes" in hub
    assert "doctor" in hub and "fixer" in hub
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


def test_agent_hub_redacts_terminal_secrets_and_disables_unsafe_escalation() -> None:
    source = _source("amoscloud_ai/api/routes/cloud_workspaces.py")

    assert 'Literal["doctor", "fixer", "autonomous", "underground"]' in source
    assert "_safe_terminal_output" in source
    assert "[redacted]" in source
    assert '"allow_force_push": False' in source
    assert '"allow_protected_branch_write": False' in source
    assert '"require_verification": True' in source
    assert "no force push" in source.lower()
    assert "no protected-branch write" in source.lower()


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
    assert "exec nano" in command
    assert "exec vim" in command
    assert "git commit -m" in command
    assert "Sync & Push" in command
