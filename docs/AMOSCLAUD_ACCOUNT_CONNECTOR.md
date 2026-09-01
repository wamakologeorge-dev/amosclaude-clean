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

General account/control-plane tools:

- `amosclaud_account` — account identity and granted scopes.
- `amosclaud_read` — read any authorized Amosclaud API resource.
- `amosclaud_write` — POST, PUT, PATCH, or DELETE any authorized `/api/v1/`
  resource.
- `amosclaud_run_autonomous` — start real Autonomous inspect, build, fix, deploy,
  or monitor work.
- `amosclaud_pipeline` — read pipeline status, jobs, logs, and evidence.

First-class native development tools:

- `amosclaud_list_repositories` — list repositories owned or shared through the
  connected Amosclaud account.
- `amosclaud_create_pull_request` — create an Amosclaud-native pull request from
  an existing bounded work branch.
- `amosclaud_list_pull_requests` — list native pull requests and Amosclaud control
  metadata.
- `amosclaud_get_pull_request` — read one native PR together with its latest
  authoritative Amosclaud Action evidence.
- `amosclaud_run_pull_request_checks` — start Amosclaud Actions for the exact head
  revision of an open native pull request.
- `amosclaud_get_pull_request_checks` — inspect Action history and checked commit
  evidence for the pull request.
- `amosclaud_control_pull_request` — close, reopen, delete, or restore a native
  pull request.
- `amosclaud_merge_pull_request` — merge only through Amosclaud's production gate;
  the gate refuses a merge unless the latest authoritative Action succeeded for
  the exact current PR head SHA.

The general read/write tools use the platform's real API routes. The first-class
development tools are intentionally thin wrappers around those same native API
routes so ChatGPT can use a clear repository/PR/CI contract without creating a
second implementation or receiving provider credentials.

## Amosclaud-first development flow

The intended development path is now:

```text
Developer / ChatGPT
        |
        v
Amosclaud Account OAuth
        |
        v
Amosclaud MCP Connector
        |
        v
Native Amosclaud repository
        |
        +--> bounded work branch
        |
        +--> native pull request
        |
        +--> Amosclaud Action / CI
        |
        +--> pipeline evidence for exact head SHA
        |
        +--> verified Amosclaud merge gate
        |
        v
Amosclaud main branch
```

GitHub, Railway, or another provider may still be configured behind Amosclaud for
mirroring, publishing, deployment, or compatibility, but an MCP client does not
need direct provider credentials to perform the native development workflow.
Provider status must not substitute for Amosclaud's own Action evidence when an
Amosclaud-native pull request is being merged.

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
- preserve exact test, pipeline, commit, pull-request, and deployment evidence;
- run Amosclaud Actions against an open native PR before merge;
- merge only when the latest authoritative Action matches the current PR head.

These are execution-integrity rules, not a read-only limitation.

## ChatGPT connection

In ChatGPT developer mode, create a custom MCP app using:

```text
https://www.amosclaud.com/connectors/amosclaud/v1/mcp
```

ChatGPT discovers the Amosclaud OAuth server, opens the Amosclaud account sign-in
and consent page, and stores the issued access and refresh tokens for the app.

After OAuth succeeds, the client should call `amosclaud_account`, then
`amosclaud_list_repositories`, before attempting write actions. Repository work
should use a bounded work branch, create a native pull request, run
`amosclaud_run_pull_request_checks`, inspect the returned evidence, and only then
call `amosclaud_merge_pull_request`.

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
