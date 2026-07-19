# Amosclaud Futuristic Autonomous Architecture

All platform entry points must point to one `AutonomousOrchestrator` in `src/agent/actions.py`.

```text
UI / API / Webhooks / Scheduled Jobs / Repository Tools
                         |
                         v
             AutonomousOrchestrator
                         |
       +-----------------+-----------------+
       |                 |                 |
   Model Gateway     Services Layer   Verification
   remote HTTP API   workspace-only   tests/compile
```

## Operational rules

1. **API decoupling** — the agent calls a configured cloud model API through standard HTTP. This package never downloads or loads model weights.
2. **Task isolation** — every task receives a designated workspace. File paths are resolved under that root and cannot escape it.
3. **One Autonomous** — planning, coding, debugging, testing, review, deployment preparation, monitoring, UI requests, and webhook requests share the same orchestrator.
4. **Authorization separation** — learning or planning never grants write, Git, deployment, founder, or owner authority.
5. **Verification before success** — compile and test evidence determines final task status.

## Structure

- `config/agent_policy.json` — global policy and safety limits.
- `src/agent/model.py` — the only cloud-model HTTP gateway.
- `src/agent/prompts.py` — strict coding, debugging, and verification prompts.
- `src/agent/actions.py` — the single Plan → Execute → Verify → Report loop.
- `src/services/code_analyzer.py` — AST and project evidence.
- `src/services/file_manager.py` — workspace-confined file operations.
- `src/services/git_service.py` — authorized Git operations.
- `src/services/runtime_exec.py` — bounded compile and test commands.
- `src/server/router.py` — `/api/v2/autonomous/run` entry point.
- `src/server/schemas.py` — task and result contracts.

## Environment

```env
AMOSCLAUD_MODEL_ENDPOINT=https://your-model-api.example.com
AMOSCLAUD_MODEL=amosclaud-agent
AMOSCLAUD_MODEL_TOKEN=
AMOSCLAUD_MODEL_TIMEOUT=90
AMOSCLAUD_WORKSPACE_ROOT=/data/repositories
```

Real secrets belong in Railway Variables, never in GitHub.
