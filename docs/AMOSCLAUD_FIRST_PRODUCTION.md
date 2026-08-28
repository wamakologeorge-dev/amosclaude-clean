# Amosclaud First Production

## Purpose

Amosclaud First Production makes Amosclaud the source of truth for Amosclaud-owned software work. GitHub, CircleCI, Railway, and Vercel may still be connected, but their status is advisory unless a workspace explicitly chooses to make an external provider authoritative.

The canonical public identity is `https://amosclauds.com`.

## Production truth

For an Amosclaud-owned repository, the authoritative sequence is:

1. Create or update an issue inside Amosclaud.
2. Create a branch and commit inside the Amosclaud repository workspace.
3. Open a native Amosclaud pull request.
4. Run **Amosclaud CI** for the exact pull-request head commit.
5. Show the CI result in Amosclaud:
   - green = authoritative Amosclaud CI success;
   - red = authoritative Amosclaud CI failure;
   - amber = pending/running;
   - gray = no authoritative result yet.
6. Allow merge only when the exact current PR head SHA has a green Amosclaud CI result.
7. Merge from the Amosclaud platform.
8. If necessary, unmerge by creating an explicit revert commit. The original merge history is never rewritten or hidden.
9. Close/reopen a PR normally. Delete is a reversible Amosclaud soft-delete; restore makes it visible again.
10. Publish first-party packages through the Amosclaud registry. Third-party integrations receive scoped, expiring Amosclaud Authority grants.

External provider states can be displayed beside the Amosclaud result, but they do not silently override Amosclaud CI.

## API surface

The new control plane is exposed before the existing production platform at:

- `GET /api/v1/amosclaud/production/manifest`
- `GET /api/v1/amosclaud/production/repositories/{repository_id}/status`
- `POST /api/v1/amosclaud/production/repositories/{repository_id}/ci`
- `GET /api/v1/amosclaud/production/repositories/{repository_id}/pull-requests`
- `POST /api/v1/amosclaud/production/repositories/{repository_id}/pull-requests/{pull_request_id}/action`

Supported PR actions are `close`, `reopen`, `delete`, `restore`, `merge`, and `unmerge`.

`merge` is rejected unless Amosclaud CI is green for the exact head SHA. `unmerge` is implemented as a new revert commit; it does not rewrite history.

## Provider-independent entry point

`amoscloud_ai.first_production_app:app` is the provider-independent ASGI entry point.

`api/index.py` exposes the same application for hosting platforms that discover that path, including Vercel-style Python deployments.

This does **not** mean a DNS name can execute software. A runtime still has to run the ASGI application.

## amosclauds.com without Railway or GitHub verification

It is possible for `amosclauds.com` to remain online and treat Amosclaud as production without using Railway or GitHub as the production verifier.

The required separation is:

- **DNS / domain identity**: `amosclauds.com` points to the chosen front door or runtime.
- **Application runtime**: Vercel, an Amosclaud-owned VM/server, Kubernetes, Docker, or another compatible runtime executes the app.
- **Production truth**: Amosclaud CI and Amosclaud repository state decide green/red and merge eligibility.
- **External adapters**: GitHub, CircleCI, Railway, Vercel deployment checks, cloud providers, and marketplaces can synchronize evidence without becoming the default authority.

Railway can therefore be removed completely if another runtime is running the Amosclaud backend.

GitHub can also be disconnected from a native Amosclaud repository. GitHub is still required only when the user intentionally imports, mirrors, pushes, opens, or manages a GitHub repository.

## Important Vercel persistence rule

The repository currently contains local SQLite and local repository/workspace storage paths. Serverless filesystems are not durable application databases.

Therefore:

- using Vercel only as the public front door is supported;
- using Vercel serverless for stateless request execution is possible;
- treating a Vercel serverless local SQLite file as durable Amosclaud production state is **not** supported;
- a full Vercel-only deployment requires durable database, repository, artifact, and workspace storage that survives serverless invocations.

Until that storage migration is complete, the safest Railway-free topology is:

`amosclauds.com -> Vercel/front door -> Amosclaud-owned persistent runtime`

or directly:

`amosclauds.com -> Amosclaud-owned persistent runtime`

## Amosclaud Action

Amosclaud Action remains the authorization and tool-discovery layer. For first-party repositories, Action should call the native Amosclaud production endpoints instead of requiring a GitHub workflow.

Third-party systems are optional adapters. Their credentials must be workspace-bound and must expire according to Amosclaud Authority policy. The current minimum grant lifetime remains 90 days.

Recommended first-party Action operations:

- issue create/update/close;
- repository inspect/write;
- PR create/list/close/reopen/delete/restore/merge/unmerge;
- CI run/status/log/evidence;
- package build/publish/inspect;
- deployment request/status;
- model invoke;
- workspace terminal and runner operations.

## First-party package policy

Amosclaud self packages should use this order:

1. source lives in an Amosclaud repository;
2. native PR contains the proposed package change;
3. Amosclaud CI verifies the exact head commit;
4. green CI enables merge;
5. merged `main` becomes eligible for package build;
6. package artifact and digest are recorded by Amosclaud;
7. Amosclaud registry is the first-party package source;
8. npm, PyPI, GitHub Packages, container registries, or other registries can be configured as third-party mirrors.

A third-party mirror failure must not retroactively turn a successfully verified Amosclaud source commit red. It should be recorded as a publication/deployment adapter failure.

## True / false operational contract

| Statement | Value | Meaning |
| --- | --- | --- |
| Amosclaud is the production authority for Amosclaud-owned repositories | TRUE | Native repository and CI state is authoritative. |
| Amosclaud can create native issues without GitHub | TRUE | Existing native issue storage is used. |
| Amosclaud can create native pull requests without GitHub | TRUE | Existing native PR storage is used. |
| Amosclaud can merge a native PR | TRUE | Merge is performed in the Amosclaud repository. |
| Amosclaud merge requires green Amosclaud CI for the exact head | TRUE | Stale or missing CI cannot unlock merge. |
| Amosclaud can close and reopen native PRs | TRUE | State changes remain inside Amosclaud. |
| Amosclaud can delete and later restore a PR | TRUE | Delete is reversible soft-delete, not history destruction. |
| Amosclaud can unmerge | TRUE | Unmerge means a new revert commit; history is preserved. |
| Green/red can be shown from Amosclaud CI | TRUE | Green is success; red is failure. |
| GitHub checks are required for Amosclaud-native merge | FALSE | GitHub is optional unless workspace policy opts in. |
| CircleCI is required for Amosclaud-native merge | FALSE | CircleCI is optional evidence. |
| Railway health is required for Amosclaud production truth | FALSE | Railway is an optional runtime adapter. |
| Vercel deployment success is required for Amosclaud production truth | FALSE | Vercel is an optional front door/runtime adapter. |
| GitHub is required to create an Amosclaud-native issue or PR | FALSE | Native repositories do not call GitHub. |
| Railway is required to run Amosclaud | FALSE | Any compatible persistent runtime can run it. |
| `amosclauds.com` can exist without Railway | TRUE | DNS can point to Vercel or an Amosclaud-owned runtime. |
| `amosclauds.com` can run application code without any runtime | FALSE | A domain is identity/routing, not compute. |
| Vercel serverless local SQLite is durable production storage | FALSE | Persistent state must live in durable storage. |
| Application code can move DNS automatically without provider authorization | FALSE | DNS remains external infrastructure and needs provider credentials/control. |
| Third-party services can use Amosclaud | TRUE | Use scoped Amosclaud Authority grants/adapters. |
| Third-party services automatically become production authority | FALSE | They remain adapters unless explicitly configured otherwise. |
| Amosclaud self packages can be verified before external registries | TRUE | Amosclaud CI and registry can be first-party. |

## Merge safety

Amosclaud must never display a green merge button because an unrelated external provider is green. The authoritative merge gate is:

`current PR head SHA == Amosclaud CI verified SHA AND Amosclaud CI status == success`

If the PR head changes after CI, the merge gate returns to non-green until the new SHA is tested.

## Failure semantics

- Test/build failure in Amosclaud CI: **red**, merge blocked.
- Amosclaud CI running: **amber**, merge blocked.
- No Amosclaud CI for current SHA: **gray**, merge blocked.
- GitHub failure while Amosclaud CI is green: external adapter failure, native merge policy remains governed by Amosclaud configuration.
- Railway failure while Amosclaud CI is green: runtime/deployment adapter failure; source verification remains green.
- Vercel failure while Amosclaud CI is green: front-door/deployment adapter failure; source verification remains green.
- Package mirror failure after successful Amosclaud package build: publication adapter failure, not source CI failure.

## Migration sequence

1. Merge this control-plane PR after repository CI passes.
2. Deploy `amoscloud_ai.first_production_app:app` on a persistent Amosclaud runtime.
3. Point the canonical API/front door at that runtime, directly or through Vercel.
4. Keep Railway configured only as a fallback while validating the new runtime.
5. Confirm login, repository storage, issue/PR state, CI runs, logs, artifacts, package storage, and backups persist after restarts.
6. Make Amosclaud CI the default merge gate in the UI.
7. Move first-party package publication to Amosclaud registry first.
8. Treat GitHub/CircleCI/Railway/Vercel as adapters in the UI.
9. After persistence and recovery tests pass, remove Railway from the production dependency chain if desired.
10. Update DNS only after the replacement runtime has verified health and rollback capacity.

## Definition of production-ready

Amosclaud First Production is production-ready only when all of these are true:

- persistent database survives restart;
- repository data survives restart;
- artifacts/packages survive restart;
- authentication and Amosclaud Authority are available;
- native issue/PR operations work;
- Amosclaud CI executes real tests and stores evidence;
- exact-SHA merge gate is enforced;
- backup and restore are tested;
- at least one production runtime is healthy;
- `amosclauds.com` TLS and DNS point to the intended front door;
- external provider outages do not corrupt Amosclaud's source-of-truth state.
