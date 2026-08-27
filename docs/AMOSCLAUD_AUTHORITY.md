# Amosclaud Authority and Action

Amosclaud Authority is the shared credential contract for Amosclaud products. It is an Amosclaud control-plane feature; it does not replace GitHub Actions and it does not configure or replace Ollama.

## Credential classes

| Credential | Prefix | Lifetime | Use |
| --- | --- | --- | --- |
| Amosclaud API key | amos_api_ | No automatic expiry | Product API clients |
| Amosclaud token | amos_token_ | No automatic expiry | CLI, IDE, MCP, and service clients |
| Amosclaud Action | amos_action_ | No automatic expiry | The Amosclaud-native Action tool caller |
| Third-party workspace grant | amos_ext_ | Required expiry, 90-day minimum | A provider authorized for one workspace |

Amosclaud-owned credentials are still revocable and rotatable. Amosclaud stores only a SHA-256 hash and returns the secret once at creation or rotation.

A third-party grant can only be created by the existing workspace owner or an Amosclaud platform administrator. It is bound to a workspace, provider, subject, and explicit scope list. The API rejects a lifetime shorter than 90 days and never accepts a non-expiring third-party grant.

## API

The authority is mounted under /api/v1/amosclaud/authority.

- GET /manifest — public identity and lifetime policy.
- GET /action/manifest — Amosclaud Action identity.
- GET /action/tools — allowlisted Action tool catalog.
- GET /action/authorize?tool=model.invoke — verify a credential and authorize one tool.
- GET /model/manifest — Amosclaud Model identity and model:invoke scope.
- GET|POST /credentials — list or issue an Amosclaud-owned API key, token, or Action credential.
- POST /credentials/{id}/rotate — revoke the old credential and issue a replacement.
- DELETE /credentials/{id} — manually revoke a credential.
- GET|POST /workspaces/{workspace_id}/third-party-grants — list or issue workspace-bound provider grants.
- POST /workspaces/{workspace_id}/third-party-grants/{id}/rotate — rotate an expiring grant.
- DELETE /workspaces/{workspace_id}/third-party-grants/{id} — revoke a grant.
- GET /verify — verify Authorization: Bearer ... or X-API-Key: ..., optionally with required_scope and workspace_id.

The Action catalog is a discovery and authorization layer. Actual execution stays in the existing governed APIs so branch protection, approvals, verification, billing, and integration-specific policies continue to apply.

The first-party verifier is accepted by the Autonomous and Copilot paths, the
connector runner, the managed VS Code terminal, the hosted-tool identity
gateway, and the OpenAI-compatible model gateway. Existing payment, support,
repository ownership, approval, and verification policies still apply after
credential authentication.

## Action tools

The catalog currently describes:

- agent answering, inspection, planning, building, fixing, testing, deployment,
  and monitoring;
- workspace list, inspect, start, stop, restart, and terminal access;
- repository list, inspect, and governed writes;
- tracked operation creation and inspection;
- CI status and governed CI runs;
- GitHub event, pull-request, and job operations;
- deployment inspection and governed deployment requests;
- Amosclaud Model invocation;
- authority verification.

Every tool has a required scope. A credential must have that scope, or authority:admin, before an Action client can use the tool. The catalog itself never returns a credential secret.

## Integration boundary

Existing GitHub Actions workflow files remain the GitHub-owned execution surface. Amosclaud Action can request a CI, pull-request, job, or deployment operation through the existing integration after authorization, but this feature does not edit .github/workflows.

Ollama remains the configured model integration. The authority adds the model:invoke identity and scope; it does not move Ollama credentials into the browser or alter Ollama environment/configuration.
