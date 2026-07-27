# Modular Plugin, MCP, and Feature Flag Architecture

Amosclaud now has a decoupled extension control plane. New trusted capabilities can be installed as drop-in Python modules or package entry points instead of being added to the primary FastAPI route list.

## High-level system architecture

```text
+------------------------------------------------------------------------+
|                         DEVELOPER INTERFACE LAYER                      |
|   Browser / xterm.js             Desktop client / local sync engine   |
+------------------------------------------------------------------------+
                                    |
                         HTTPS and secure WebSocket
                                    v
+------------------------------------------------------------------------+
|                            API CONTROL PLANE                           |
|  FastAPI core  <->  Auth and tier service  <->  Feature flag service |
|       |                         |                         |             |
|       +-------------------------+-------------------------+             |
|                          Plugin registry                                |
+------------------------------------------------------------------------+
             |                         |                         |
             v                         v                         v
+----------------------+  +------------------------+  +------------------+
| Compute engine       |  | Storage control plane  |  | MCP client mgr   |
| Docker/Kata/MicroVM  |  | GCP/AWS disk growth    |  | Scoped servers   |
| bounded resources    |  | snapshot + fs verify   |  | tool allowlists  |
+----------------------+  +------------------------+  +------------------+
             |                         |                         |
             +-------------------------+-------------------------+
                                       v
+------------------------------------------------------------------------+
|                    AMOSCLAUD AUTONOMOUS AGENT LAYER                    |
|       One orchestrator  <->  registered agent tools and MCP tools     |
+------------------------------------------------------------------------+
```

The public API process coordinates policy and durable jobs. It does not run privileged disk commands, expose infrastructure credentials to project containers, or treat every installed integration as automatically available to every user.

## Modular extension architecture

```text
                         +------------------------+
                         |    Core API Engine     |
                         |       FastAPI          |
                         +-----------+------------+
                                     |
                         Existing extension host
                                     |
                         +-----------v------------+
                         |     Plugin Registry    |
                         | importlib / pkgutil /  |
                         | Python entry points    |
                         +-----------+------------+
                                     |
          +--------------------------+--------------------------+
          |                          |                          |
          v                          v                          v
+-------------------+      +-------------------+      +-------------------+
| MCP control plane |      | Custom LLM plugin |      | Storage manager   |
| servers and tools |      | model adapter      |      | capacity adapter |
+-------------------+      +-------------------+      +-------------------+
```

The primary `amoscloud_ai/main.py` does not import the MCP manager, feature flag routes, or extension routes. The already-established control-bus router is the stable host. It discovers extensions and mounts their contributions before the FastAPI application includes that router.

## Plugin discovery

Amosclaud discovers trusted plugins from three sources:

1. **Drop-in modules** under `amoscloud_ai/plugins/`.
2. **Installed package entry points** in the `amosclaud.plugins` group.
3. **Operator-selected modules** listed in `AMOSCLAUD_PLUGIN_MODULES`.

Third-party Python packages execute inside the Amosclaud control-plane process. They must be reviewed and trusted before installation. Feature flags control user exposure; they are not a sandbox for untrusted Python code.

### Drop-in plugin example

Create `amoscloud_ai/plugins/security_scanner.py`:

```python
from fastapi import APIRouter

from amoscloud_ai import feature_flags
from amoscloud_ai.extensions import PluginContext, PluginManifest

router = APIRouter()


@router.get("/status")
def scanner_status() -> dict:
    return {"state": "ready"}


class SecurityScannerPlugin:
    manifest = PluginManifest(
        plugin_id="security-scanner",
        name="Security Scanner",
        version="1.0.0",
        api_prefix="/api/v1/plugins/security-scanner",
        capabilities=("security.scan",),
    )

    def register(self, context: PluginContext) -> None:
        context.add_router(router)
        context.define_flag(
            feature_flags.FlagDefinition(
                key="security.advanced_scanner",
                name="Advanced security scanner",
                description="Expose the advanced repository scanner.",
                required_tiers=("full",),
                owner_plugin=context.plugin_id,
            )
        )
        context.add_agent_tool("scan", run_scan)


def run_scan(repository_id: int) -> dict:
    return {"repository_id": repository_id, "queued": True}


def create_plugin() -> SecurityScannerPlugin:
    return SecurityScannerPlugin()
```

Restart the control plane. The module is discovered with `pkgutil.iter_modules`, imported with `importlib`, validated against the plugin protocol, and mounted under its declared plugin prefix.

### Installed package entry point

An external package can declare:

```toml
[project.entry-points."amosclaud.plugins"]
security_scanner = "company_amosclaud_plugin:create_plugin"
```

A plugin can contribute:

- FastAPI routers under `/api/v1/plugins/<plugin-id>`;
- feature flag definitions;
- named agent tools;
- terminal command adapters;
- MCP server factories;
- health checks;
- startup and shutdown hooks.

Contribution names are namespaced by plugin ID when added to the global registry.

## Feature flag evaluation

Flags use this precedence:

```text
workspace override
    -> user override
    -> tier override
    -> global enabled state
    -> deterministic percentage rollout
```

The rollout bucket is a stable SHA-256-derived value from the flag key and workspace/user subject. The same subject remains in the same rollout cohort across processes and restarts.

Built-in flags include:

- `mcp.integrations`;
- `extensions.third_party`;
- `workspace.live_collaboration`;
- `ai.model_switching`;
- `storage.high_capacity`.

The high-capacity storage route requires `storage.high_capacity` for requests above 512 GiB. This allows 1 TiB and 2 TiB profiles to be enabled only for approved users, workspaces, or tiers.

## MCP client manager

MCP servers are registered with:

- an ID and human-readable description;
- a Streamable HTTP endpoint;
- an optional authentication header name;
- an environment-variable reference for the credential;
- an enabled state;
- a controlling feature flag;
- an optional exact tool allowlist;
- a timeout;
- user, workspace, and tier scopes.

Raw credentials are never stored in the database. For example, the registry stores `MCP_JIRA_TOKEN`, while the actual secret remains in the Railway, Kubernetes, or host secret manager.

Before a tool call, Amosclaud verifies:

1. the user is authenticated;
2. the server is enabled;
3. its feature flag evaluates to enabled;
4. its user/workspace/tier scope matches;
5. the endpoint passes URL and network policy;
6. the tool appears in the allowlist when one is configured;
7. the argument payload stays below the configured limit;
8. redirects are disabled;
9. initialization and the tool call complete within the timeout;
10. the result or failure is recorded in the MCP audit log.

The client uses the MCP Python SDK `ClientSession` and Streamable HTTP transport. The dependency is pinned to `mcp>=1.27,<2` so the v1 API cannot be silently replaced by a future incompatible major release.

## Administrator control panel

Open:

```text
/admin/extensions
```

The panel displays live plugin status and health checks, creates and updates feature flags, adds targeted overrides, registers MCP endpoints, assigns MCP scopes, and probes `tools/list` without exposing credentials.

## Safety boundaries

- Only trusted Python packages may be installed as plugins.
- Plugin API routes must remain under `/api/v1/plugins/`.
- MCP public endpoints require HTTPS unless private endpoints are explicitly enabled by the operator.
- MCP redirects are disabled.
- Private and special-network addresses are rejected by default.
- MCP secrets are environment references, not database values.
- A feature flag defaults to disabled when undefined.
- Per-workspace and per-user decisions override broader tier and rollout decisions.
- High-capacity storage remains snapshot-gated and is executed only by the privileged storage controller.
- No plugin or MCP registration grants automatic protected-branch, deployment, billing, or secret access.
