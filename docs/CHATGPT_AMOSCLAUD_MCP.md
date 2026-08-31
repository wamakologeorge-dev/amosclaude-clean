# ChatGPT ↔ Amosclaud MCP Gateway

Amosclaud exposes a first-party Model Context Protocol (MCP) gateway so an authorized MCP client can work through **Amosclaud itself** instead of receiving direct GitHub, Railway, filesystem, database, or infrastructure credentials.

The same gateway can run on hosted Amosclaud infrastructure or on a future physical Amosclaud computer. The client talks to Amosclaud; Amosclaud decides which local or external engine performs the work.

## Architecture

```text
ChatGPT / MCP client / Amosclaud Desktop / Amosclaud PC
                         |
                         | HTTPS + Amosclaud credential
                         v
                https://amosclauds.com/mcp/
                         |
                         v
                 Amosclaud MCP Server
                         |
          +--------------+----------------+
          |                               |
          v                               v
/api/v1/mcp-gateway                 Autonomous Agent
          |                               |
          v                               v
Native Amosclaud repositories       Actions / Pipelines
Branches / files / commits          Build / test / fix / deploy
          |                               |
          +--------------+----------------+
                         |
                         v
              Amosclaud Control Plane
                         |
            optional provider adapters
        (GitHub, cloud, external runners, etc.)
```

The provider boundary is intentional. An MCP client should never need a GitHub token merely to use Amosclaud. If Amosclaud chooses to mirror or publish a repository to an external provider, that is an Amosclaud-controlled integration behind the gateway.

## Endpoint

The Streamable HTTP MCP endpoint is:

```text
https://amosclauds.com/mcp/
```

For local or physical-node development the same server can be exposed from the machine's HTTPS address. A remote MCP client needs a network-reachable HTTPS endpoint; the Amosclaud service itself does not require a browser UI to operate.

## Authentication

The current direct connection accepts an Amosclaud bearer credential through the existing authority layer. The gateway recognizes protected Amosclaud MCP/Autonomous keys and user-scoped Amosclaud credentials.

Server configuration:

```text
AMOSCLAUD_API_URL=https://amosclauds.com
AMOSCLAUD_MCP_ACCESS_KEY=<protected-owner-or-service-key>
```

Never commit the raw key. User-scoped credentials should be issued by Amosclaud with only the scopes they need.

Native repository operations use these scopes when a scoped authority credential is supplied:

- `repository:read`
- `repository:write`

Administrator credentials retain administrator behavior. Existing legacy Autonomous/provider credentials continue to use their established account-level permissions while the product transitions to scoped credentials.

## MCP tools

### Read-only connection and repository tools

- `amosclaud_status`
- `amosclaud_connection`
- `list_repositories`
- `get_repository`
- `list_repository_tree`
- `read_repository_file`
- `list_repository_branches`
- `list_repository_commits`
- `amosclaud_agent_profile`
- `get_pipeline_result`
- `wait_for_pipeline_result`
- `list_recent_pipelines`

### Write or execution tools

- `create_repository`
- `create_repository_branch`
- `write_repository_file`
- `delete_repository_file`
- `run_autonomous`

Write operations execute through Amosclaud's native repository provider. A successful file write returns the real Amosclaud commit SHA. Autonomous work returns pipeline evidence that must be checked before a client reports success.

## Physical Amosclaud computer

A physical Amosclaud computer can run the same software stack instead of becoming a separate product implementation.

```text
Physical Amosclaud Computer
├── Amosclaud Control Plane
├── Amosclaud Repository Provider
├── Amosclaud MCP Gateway
├── Amosclaud Agent
├── Amosclaud Actions / Runner
├── SpaceCodeMe workspace runtime
├── Model gateway
└── Storage
```

This allows the product to keep working without depending on a website as the execution environment. The website becomes one interface to the computer/control plane, not the computer itself.

A useful target boot contract is:

```text
Power on
  -> Amosclaud services start
  -> repository/storage volumes mount
  -> MCP endpoint becomes healthy
  -> Agent and Actions become ready
  -> local LAN or authorized remote clients can connect
```

## ChatGPT connection status

The Amosclaud side now has the Streamable HTTP MCP transport and native bearer-authenticated repository gateway required for direct MCP clients.

Connecting it as a custom ChatGPT app is a separate product-side registration step in ChatGPT web. ChatGPT support for custom MCP apps, write actions, and mobile clients depends on the user's ChatGPT plan/workspace and current product availability.

For a broadly distributed multi-user ChatGPT app, Amosclaud should add standards-based OAuth authorization for `/mcp/` rather than sharing one owner key. That production OAuth layer should provide per-user consent, scoped access, refresh tokens, revocation, and MCP protected-resource metadata. Until that is implemented and verified, the bearer-key path is intended for owner/developer/service connections.

## Verification checklist

Before describing a deployed connection as complete, prove all of the following against the target deployment:

1. `/health` reports healthy.
2. `/mcp/` accepts a valid Amosclaud credential and rejects an invalid one.
3. `amosclaud_connection` resolves the expected Amosclaud account.
4. `list_repositories` returns only repositories that account may see.
5. A read-scoped credential cannot use repository write tools.
6. `write_repository_file` produces a real commit SHA in the native repository.
7. `run_autonomous` returns a real pipeline ID and its terminal result is inspectable.
8. No GitHub, Railway, database, or filesystem credential is exposed to the MCP client.
9. The same checks pass after a service restart.

Passing those checks is the evidence that the client is connected to Amosclaud rather than merely displaying an Amosclaud-branded interface.
