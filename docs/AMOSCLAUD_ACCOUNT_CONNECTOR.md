# Amosclaud Account Connector

The Amosclaud Account Connector is a remote Model Context Protocol (MCP) server
that lets ChatGPT, Codex, and other MCP clients connect directly to an Amosclaud
account.

It is separate from the legacy owner-key MCP endpoint.

## Unique endpoints

- MCP resource server: `https://www.amosclaud.com/connectors/amosclaud/v1/mcp`
- OAuth issuer: `https://www.amosclaud.com/connectors/amosclaud/v1/oauth`
- Authorization server metadata:
  `https://www.amosclaud.com/.well-known/oauth-authorization-server/connectors/amosclaud/v1/oauth`
- Protected resource metadata:
  `https://www.amosclaud.com/.well-known/oauth-protected-resource/connectors/amosclaud/v1/mcp`

## Account connection

The connector implements OAuth authorization-code flow with PKCE S256, dynamic
client registration, short-lived access tokens, refresh-token rotation, exact
redirect-URI matching, token revocation, hashed token storage, and account-bound
scopes.

A user signs in with their Amosclaud account and grants the scopes requested by
the MCP client. The resulting token identifies the Amosclaud user and never
contains the user's password, session cookie, GitHub token, or provider secrets.

## Tools

- `amosclaud_account` — account identity and granted scopes.
- `amosclaud_read` — read any authorized Amosclaud API resource.
- `amosclaud_write` — POST, PUT, PATCH, or DELETE any authorized `/api/v1/`
  resource.
- `amosclaud_run_autonomous` — start real Autonomous inspect, build, fix, deploy,
  or monitor work.
- `amosclaud_pipeline` — read pipeline status, jobs, logs, and evidence.

The general read/write tools use the platform's real API routes. This keeps the
connector aligned with new Amosclaud capabilities without creating a second
implementation for every feature.

## Scopes

- `account:read`
- `platform:read`
- `platform:write`
- `repositories:read`
- `repositories:write`
- `tasks:read`
- `tasks:write`
- `deployments:write`
- `admin:write` — only available to an Amosclaud administrator

## Repository rules

The connector has full read/write capability within the connected account's
scopes. Repository execution must still use Amosclaud's governed repository
layer:

- use bounded work branches;
- do not force-push;
- do not rebase published work;
- do not write directly to protected default branches;
- preserve exact test, pipeline, commit, pull-request, and deployment evidence.

These are execution-integrity rules, not a read-only limitation.

## ChatGPT connection

In ChatGPT developer mode, create a custom MCP app using:

```text
https://www.amosclaud.com/connectors/amosclaud/v1/mcp
```

ChatGPT discovers the Amosclaud OAuth server, opens the Amosclaud account sign-in
and consent page, and stores the issued access and refresh tokens for the app.

Full MCP write/modify actions in ChatGPT currently depend on the ChatGPT plan and
workspace settings. The same remote MCP server can also be used from the OpenAI
API by supplying the server URL and OAuth access token.

## Runtime

The production entry point is:

```text
amoscloud_ai.connected_app:app
```

It mounts, in order:

1. Amosclaud connector OAuth routes;
2. the unique account MCP endpoint;
3. the complete existing Amosclaud platform and legacy `/mcp` endpoint.

No existing route is removed.
