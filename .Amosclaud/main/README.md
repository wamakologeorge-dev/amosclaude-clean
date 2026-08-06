# `.Amosclaud/main`

This directory is the repository-level control point for the Amosclaud ecosystem.
It does not replace the platform packages. It connects and verifies them.

The ecosystem manifest connects these surfaces as one platform:

- `amoscloud_ai` — canonical FastAPI runtime, accounts, agents and platform APIs;
- `amosclaud_mcp` — standalone Model Context Protocol server;
- `amosclaud_bot` — GitHub events, repair callbacks and repository automation;
- `web` — account, dashboard, terminal and developer experience;
- `tests` — deterministic verification and regression contracts;
- `.github/workflows` — CI, repair, security and delivery automation;
- `docs` — architecture, API, deployment and developer documentation.

The ecosystem manifest identifies the canonical runtime, developer interfaces,
GitHub automation, MCP server, web application, tests, documentation and CI
workflows. The verification script rejects temporary, generated and archive
clutter in the repository root and confirms that every required subsystem still
exists.

The `Amosclaud Main Clean` workflow runs the verification on pull requests. When
the manifest, required paths and root-cleanliness policy pass, the workflow posts
this idempotent pull-request comment:

```text
.Amosclaud/main clean_100%
```

The comment is evidence that the checked commit passed the ecosystem contract.
It must never be posted when required packages are missing or forbidden root
artifacts are present.
