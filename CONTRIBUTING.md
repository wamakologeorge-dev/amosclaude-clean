# Contributing to Amosclaud

Amosclaud is a developer-first, self-hosted engineering control plane. Contributions are welcome from developers, testers, technical writers, designers, security reviewers, and infrastructure engineers.

## Development principles

- `main` is the only canonical product and deployment branch.
- Feature branches are temporary review lanes, not separate Amosclaud products.
- Existing services, legacy applications, and GitHub-native applications remain part of one ecosystem.
- Do not disable a working service merely to make a different feature pass. Connect both through the shared pipeline, adapter, event, artifact, or compatibility contract.
- Amosclaud Autonomous is the primary execution runtime; external model providers are optional integrations.
- Features must return real results and explicit blockers. Never report unverified work as successful.
- Repository writes, merges, deployment, destructive operations, and sensitive configuration remain policy- and approval-controlled.
- Every new file must have an identifiable runtime, test, documentation, configuration, migration, or contributor purpose.
- Security, tenant ownership, audit evidence, and self-hosting take priority over convenience.

## Before opening an issue

Search existing issues and pull requests first. Include enough evidence for another contributor to reproduce or evaluate the request.

A useful bug report includes:

- the Amosclaud version or commit SHA;
- operating system and deployment environment;
- the affected service, route, workflow, or user path;
- exact reproduction steps;
- expected and actual behavior;
- sanitized logs or workflow output;
- whether the failure is consistent or intermittent;
- the smallest known repository or input that reproduces it.

Do not place tokens, cookies, passwords, private keys, private repository content, personal information, or unredacted environment variables in an issue.

Feature proposals should explain the user problem, how the capability joins the existing ecosystem, the expected evidence of success, and which approval or security boundaries apply.

See [the label taxonomy](docs/LABELS.md) for `area:*`, `type:*`, `size:*`, `priority:*`, and `status:*` labels.

## Local setup

Requirements:

- Python 3.11 or newer;
- Git;
- Docker and Docker Compose for full-stack, node, sandbox, or Java pod testing.

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
python3 -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

Get a deterministic local result before starting the full platform:

```bash
amosclaud-quick . --objective "Inspect this repository"
```

Run the standard validation suite:

```bash
make test
make quality
make build
```

The explicit equivalents are:

```bash
python scripts/workspace_task.py test
python scripts/workspace_task.py quality
python scripts/workspace_task.py build
```

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the local API, Docker self-hosting, execution nodes, Java pods, and GitHub-native triggers.

## Contribution workflow

1. Create or reference an issue for substantial behavior changes.
2. Create a focused branch from the latest `main`.
3. Identify the existing service or contract that owns the behavior.
4. Make the smallest complete change that solves the problem without disconnecting another service.
5. Add or update focused tests.
6. Run formatting, import-order, lint, tests, and build checks locally.
7. Add documentation, migration notes, or visuals when behavior or setup changes.
8. Open a pull request with evidence and known limitations.
9. Address review findings on the same pull-request branch.
10. Merge manually only after required checks pass and the repository owner approves.

Recommended branch names:

```text
feature/<short-name>
fix/<short-name>
docs/<short-name>
security/<short-name>
maintenance/<short-name>
```

Do not create a second `main`, bypass branch protection, or rebase an unrelated history to make a pull request appear clean.

## Pull request requirements

Every pull request should include:

- the problem and user impact;
- the implementation approach;
- affected services, routes, files, and data contracts;
- how existing and legacy behavior remains compatible;
- tests and commands executed;
- workflow or runtime evidence;
- screenshots for visible interface changes;
- deployment, configuration, or migration notes;
- security and approval implications;
- known limitations and follow-up work.

Use the repository pull-request template. Do not mix unrelated refactors, formatting sweeps, dependency upgrades, and feature work in one pull request.

A pull request is not ready merely because code was committed. It is ready when the change has relevant tests, truthful evidence, documentation, and a reviewable scope.

## Pipeline and runtime contributions

Changes to pipelines, workers, nodes, Java pods, or PipeFail must preserve the shared contract:

```text
authenticated owner
→ pipeline ID
→ dependency-aware task
→ capability or resource assignment
→ ordered events
→ artifacts and evidence
→ approval where required
→ verified result or exact failure
```

Pipeline changes should answer these questions:

- What creates the task?
- Which worker or node capability executes it?
- What resources are leased and when are they released?
- What evidence proves completion?
- Which failures are retryable?
- What does PipeFail record and how is work reassigned?
- What state is visible to the user?
- Which actions require approval?
- How are duplicate events or executions prevented?

A runtime must not receive unrestricted access to production secrets, other users' repositories, the Docker socket, or host files outside its configured workspace.

## GitHub Actions contributions

Read [docs/GITHUB_ACTIONS.md](docs/GITHUB_ACTIONS.md) before adding or changing a workflow.

A workflow change must document:

- trigger events and path scope;
- minimum token permissions;
- concurrency and cancellation behavior;
- timeout and retry behavior;
- artifacts or diagnostics;
- fork pull-request behavior;
- secret boundaries;
- interaction with the Amosclaud Native Pipeline;
- whether it changes write, merge, or deployment policy.

Pin third-party actions to full commit SHAs. Keep read-only jobs read-only.

## Code quality

- Keep functions focused and readable.
- Prefer explicit types and structured request and response models.
- Validate user-controlled paths, branches, URLs, commands, identifiers, and resource values.
- Never commit secrets, tokens, credentials, private keys, or real customer data.
- Preserve backward compatibility unless a breaking change is explicitly documented and reviewed.
- Return truthful states such as queued, scheduled, running, waiting for approval, completed, failed, cancelled, or rolled back.
- Avoid catch-all exception handling that hides failure context.
- Do not fabricate service health, test results, model output, deployment state, or telemetry.
- Keep generated files and build artifacts out of the repository unless they are intentional, reviewed release assets.

## Tests and evidence

Add the smallest test that proves the behavior and prevents regression. Depending on the change, evidence may include:

- unit or integration test output;
- API response examples;
- a workflow run and job log;
- a generated artifact checksum;
- a Java pod `result.json` or `pipefail.json`;
- PipeFail telemetry;
- a sanitized screenshot;
- a compatibility test for a legacy application;
- a complete repository inventory digest.

Use [docs/DEMO.md](docs/DEMO.md) for reproducible pipeline, node, Java pod, and trigger demonstrations.

Screenshots and recordings must not expose personal data, tokens, cookies, private repository names, internal hostnames, or secret values. State the commit or release represented by the visual.

## Documentation style

Documentation should help a new developer answer:

1. What problem does this component solve?
2. How does it connect to the Amosclaud ecosystem?
3. How do I run it?
4. How do I verify it?
5. What can fail?
6. What permissions or approvals are required?

Avoid screenshots as the only setup instruction. Include copyable commands and text descriptions for accessibility and future maintenance.

## Autonomous runtime rules

Build, test, review, deploy, and monitor actions should route through Amosclaud Autonomous with `use_agent: false` by default. Optional model reasoning may be added behind an explicit user choice, but it must never be required for native repository or deployment workflows.

A model timeout, refusal, empty response, or unavailable provider is a blocker, not a successful repository action.

## Security issues

Do not open a public issue for a suspected vulnerability. Follow [SECURITY.md](SECURITY.md). Provide the smallest safe reproduction and avoid accessing data or systems beyond your authorization.

## License

By contributing, you agree that your contribution may be distributed under the repository's [MIT License](LICENSE). Commercial service terms apply only to separately provided paid or managed offerings and do not remove MIT rights for repository source code.
