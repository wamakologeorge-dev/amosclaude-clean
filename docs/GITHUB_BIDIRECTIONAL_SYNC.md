# Amosclaud ⇄ GitHub bidirectional synchronization

This design connects Amosclaud workspaces to GitHub user and organization repositories without hard-coded runner paths, unpinned SSH actions, or destructive synchronization.

## 1. Platform to GitHub

A signed-in developer connects GitHub through Amosclaud. The authorization requests:

- `repo` for repository code and private-repository access;
- `workflow` for publishing `.github/workflows/*` files;
- `read:org` for listing organization memberships;
- `read:user` and `user:email` for account identity.

The repository creation dialog calls `GET /api/v1/github/organizations` and lets the developer choose their personal account or an organization visible to the authorization. GitHub still performs the final permission check. Organization owners may need to approve the OAuth app, authorize SSO, or permit members to create repositories.

New repositories are created through either:

- `POST /user/repos` for the connected personal account; or
- `POST /orgs/{organization}/repos` for an organization.

Amosclaud validates the selected local branch and existing remote before creating anything on GitHub. It then commits only the active dirty branch, pushes the named local branch rather than an arbitrary `HEAD`, sets the real GitHub default branch for a newly created repository, stores GitHub's immutable repository ID and canonical full name, and removes the credential from the persisted remote URL.
Amosclaud then commits the local project, pushes the selected branch, stores the real GitHub repository identity, and removes the credential from the persisted remote URL.

Existing native Amosclaud repositories can be published through:

```http
POST /api/v1/github/repositories/{repository_id}/publish
```

The selected visibility must match an existing target repository. Amosclaud will not push a private workspace to an existing public target, replace a GitLab or private origin, or overwrite an unrelated GitHub repository that already contains history. Import the target repository first when it already exists.
Amosclaud will not push a native project over an unrelated GitHub repository that already contains history. Import the target repository first when it already exists.

## 2. GitHub to platform

The GitHub App webhook URL is:

```text
https://www.amosclaud.com/api/v1/agent/github/webhook
```

Configure the GitHub App with a webhook secret and subscribe to both:

- `push`, for code synchronization; and
- `repository`, for rename and transfer mapping updates.

The GitHub App needs read-level **Metadata** repository permission to receive repository events. Amosclaud validates the exact request bytes with `X-Hub-Signature-256` and constant-time comparison before accepting the event. In production, a missing webhook secret fails closed.

A valid push is queued only when the server-managed `repository_sync.direction` and `repository_sync.github_to_platform` policy allow inbound synchronization. The worker:

1. finds mapped workspaces by GitHub's immutable repository ID, with a case-insensitive full-name fallback for legacy rows;
2. refreshes the canonical full name when GitHub renames or transfers the repository;
3. processes only the mapped GitHub default branch;
4. blocks when the workspace has uncommitted files;
5. blocks a detached HEAD containing unreferenced committed work;
6. fetches using the encrypted connected authorization, isolating an expired authorization to that one workspace;
7. fast-forwards only when the local branch commit is an ancestor of the remote commit;
8. refuses to overwrite ahead or diverged history;
9. records every attempt separately from the timestamp of the last successful synchronization.

This means a platform push may produce a harmless webhook round trip: the worker sees that the workspace already matches GitHub and records `current` as a successful synchronization.
Configure the GitHub App with a webhook secret and subscribe to the `push` event. Amosclaud validates the exact request bytes with `X-Hub-Signature-256` and constant-time comparison before accepting the event.

A valid push queues a mapped-workspace synchronization job. The worker:

1. finds local repositories mapped to the GitHub `full_name`;
2. processes only the mapped default branch;
3. blocks when the workspace has uncommitted files;
4. fetches using the encrypted connected authorization;
5. fast-forwards only when the local commit is an ancestor of the remote commit;
6. refuses to overwrite ahead or diverged history;
7. records the latest sync state and remote SHA.

This means a platform push may produce a harmless webhook round trip: the worker sees that the workspace already matches GitHub and records `current`.

## 3. Why no SSH deployment action

The platform does not use `appleboy/ssh-action@master` or a path such as `/home/runner/work/.../data/repositories/1`.

Those paths belong to an ephemeral GitHub-hosted runner and cannot address Railway or another Amosclaud node reliably. Instead:

- GitHub sends a signed event to the public Amosclaud API;
- Amosclaud resolves the repository ID from its database;
- the platform worker performs the safe pull inside the configured persistent repository root;
- the deployment/runtime layer decides whether to rebuild or restart the project.

No SSH private key is copied into every repository.

## 4. Required production configuration

```text
GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET
GITHUB_REPOSITORY_CALLBACK_URL=https://www.amosclaud.com/api/v1/github/callback
GITHUB_TOKEN_ENCRYPTION_KEY
GITHUB_APP_WEBHOOK_SECRET
GITHUB_APP_SLUG=amosclaud-platform
AMOSCLAUD_GATEWAY_CONFIG=/app/config/gateway.yaml
AMOSCLAUD_ORGANIZATION_SETTINGS=/app/config/organization-settings.json
```

Install the Amosclaud GitHub App on each organization and select the repositories it may access. Prefer GitHub App installation tokens for long-term organization automation because their access is repository-scoped and revocable by the organization owner.

## 5. Central cloud policy

`config/gateway.yaml` defines routing, model order, telemetry, network domains, and sandbox defaults.

`config/organization-settings.json` defines immutable organization policy, including the bidirectional synchronization safety rules. The platform exposes non-secret status through:

```http
GET /api/v1/platform/cloud-configuration
```

There is intentionally no API that lets a project developer mutate these server-managed files.

## 6. Container development environment

The Dev Container uses `.devcontainer/docker-compose.yml` to start:

- the Amosclaud application container;
- PostgreSQL 16 for both `DATABASE_URL` and `AMOSCLAUD_PLATFORM_DATABASE_URL`;
- PostgreSQL 16;
- Redis 7;
- Docker-in-Docker for project container builds.

Open the repository in a Dev Container and run:

```bash
python -m pytest -q tests/test_github_organization_pushback.py
uvicorn amoscloud_ai.main:app --host 0.0.0.0 --port 8000 --reload
```

The development database uses trust authentication only inside the isolated Compose network. Production databases and secrets remain in Railway variables or another secret manager and must not be committed.
The development credentials in the Compose file are local-only defaults. Production secrets remain in Railway variables or another secret manager and must not be committed.
