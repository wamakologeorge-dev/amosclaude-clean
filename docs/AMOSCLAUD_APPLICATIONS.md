# Amosclaud Applications

Amosclaud Applications are installable developer integrations that run through Amosclaud's own identity, permission, workspace, agent, and audit boundaries. They are not required to be desktop or mobile apps. A developer creates one application definition and can distribute it to authorized Amosclaud organizations.

## Core model

- **Developer Application** — the package a developer creates and versions.
- **Application Installation** — an organization-specific authorization of that application.
- **Granted scopes** — the exact capabilities an organization approved for one installation. Installations can never grant scopes the application did not request.
- **Application token** — an installation credential. The raw value is returned only when created; Amosclaud stores only its SHA-256 digest and a display prefix.
- **Audit event** — immutable evidence for application creation, installation, token issuance, and token revocation.

## Distribution

Applications can be `private`, `shared`, or `public`. Private applications are installable only in their owner organization. Shared and public applications may be installed into another organization by an administrator of that organization. Marketplace discovery is a separate product surface; public status never bypasses organization approval.

## Permission scopes

The first-party scope catalog includes repository read/write, terminal execution, Amosclaud Agent use, SpaceCodeMe access, actions, staging/production deployment, storage, model, and audit read capabilities. Sensitive capabilities remain separately grantable so an organization can let an application inspect and test code without granting deployment or broader workspace authority.

## API flow

1. Create an application under an organization with `POST /api/v1/organizations/{organization_id}/applications`.
2. An administrator of the target organization installs it with `POST /api/v1/applications/{application_id}/installations` and chooses a subset of requested scopes.
3. Create a credential with `POST /api/v1/installations/{installation_id}/tokens`.
4. Use the returned token from the external integration. Amosclaud does not return that raw token again.
5. Revoke credentials with `DELETE /api/v1/installations/{installation_id}/tokens/{token_id}`.

The platform Settings surface is available at `/settings` and groups Access, Code/Planning/Automation, Security/Quality, Integrations, Domain/Network, Storage/Compute, and Observability. Amosclaud Agent and Amosclaud SpaceCodeMe are first-party capabilities rather than GitHub Copilot/Codespaces labels.
