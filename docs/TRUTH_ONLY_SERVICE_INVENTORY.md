# Amosclaud truth-only service inventory

This inventory records what the repository contains. It does not prove that a production deployment is configured or healthy. A service is operational only when its runtime check succeeds in the deployed environment.

## Visible and repository-backed

### Authentication

Repository evidence:
- session authentication routes are mounted under `/api/v1`
- authenticated pages redirect to `/login` when no valid session exists

Truthful statement:
- Amosclaud contains account and session authentication code.
- A specific deployment may still fail if its database or persistent storage is unavailable.

### Chat and Autonomous request route

Repository evidence:
- `POST /api/v1/agent/run` accepts authenticated requests
- the route can return a conversational response or dispatch an existing governed pipeline

Truthful statement:
- Amosclaud can accept authenticated chat or agent requests.
- Execution depends on the selected route, repository state, runtime dependencies, permissions, and configuration.
- A queued or accepted request is not proof of successful execution.

### Native repositories

Repository evidence:
- repository routes are mounted under `/api/v1`
- the repository page calls authenticated APIs to list repositories, create repositories, open workspaces, and write files

Truthful statement:
- Amosclaud contains native repository management functions.
- Results must come from the repository API response; the browser must not invent a repository or commit.

### Bundle creation

Repository evidence:
- bundle creation code builds a real archive and manifest from safe workspace files
- the bundle manifest records file paths, sizes, hashes, source bytes, and an archive SHA-256

Truthful statement:
- Amosclaud contains a real bundle builder.
- Bundle creation is available only when the authenticated bundle route, workspace folder, and output storage are usable.
- A bundle result must include the returned manifest and archive evidence.

### Health

Repository evidence:
- health routes are mounted by the FastAPI application

Truthful statement:
- health must be read from the live health response.
- Static labels such as online, ready, healthy, or running are not evidence.

## Configuration-dependent

These repository areas may require secrets, external accounts, persistent volumes, network access, or additional running services. Their presence in source code does not prove production operation:

- GitHub OAuth and GitHub repository operations
- provider and model endpoints
- deployments and production publishing
- service keys, webhooks, mail, billing, Wi-Fi, community, and external connectors
- any model-server or separate runtime process

The interface must show these as unavailable or configuration-required until a real runtime check succeeds.

## Not permitted during the truth-only freeze

- placeholder or sample result records
- fabricated dashboard totals
- static success, ready, online, healthy, or deployed claims
- announcing a service because a file or route name exists
- creating another service to hide an unavailable dependency
- treating a planned, queued, or accepted operation as completed

## Current public interface rule

The main interface exposes Chat, Repository, and a real server check. Additional services should remain hidden until their existing implementation and runtime operation are verified.