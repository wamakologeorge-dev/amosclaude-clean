# GitHub Actions and Pipeline Automation

Amosclaud uses GitHub Actions for two different responsibilities:

1. **specialized verification workflows** test, lint, build, package, scan, and audit the repository;
2. **the Amosclaud Native Pipeline bridge** converts GitHub events into the same durable cooperation pipeline used by the web Control Plane, agents, workers, execution nodes, Java pods, telemetry, and PipeFail.

The bridge does not disable or replace existing workflows. It gives their repository events a common orchestration and evidence path.

## Status badges

The repository README displays the primary pull-request gate and native-pipeline status:

```markdown
[![Fast PR Gate](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/fast-pr-gate.yml/badge.svg?branch=main)](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/fast-pr-gate.yml)

[![Amosclaud Native Pipeline](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-native-pipeline.yml/badge.svg?branch=main)](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-native-pipeline.yml)
```

A badge shows the latest workflow result for the selected branch. It is not proof that every repository workflow, external integration, deployment, or runtime node is healthy.

## Fast PR Gate

Workflow: [`.github/workflows/fast-pr-gate.yml`](../.github/workflows/fast-pr-gate.yml)

The Fast PR Gate runs for pull requests targeting `main` when Python, YAML, requirements, or `pyproject.toml` files change. It:

- checks out the complete comparison history;
- uses Python 3.12 and a pinned `uv` setup action;
- calculates the changed files between the pull-request base and head;
- runs formatting, import-order, lint, and focused tests through `scripts/ci/fast_gate.py`;
- uploads diagnostics only when the gate fails;
- cancels an older in-progress run when a newer commit reaches the same pull request.

This gate is intentionally fast. It is not a replacement for the complete test, build, package, Docker, security, or runtime workflows.

## Amosclaud Native Pipeline

Workflow: [`.github/workflows/amosclaud-native-pipeline.yml`](../.github/workflows/amosclaud-native-pipeline.yml)

### Triggers

The workflow responds to:

| GitHub event | Default cooperation mode | Scope |
|---|---:|---|
| `push` | `build` | every changed tracked path |
| `pull_request` opened, reopened, synchronized, or ready | `build` | every changed tracked path |
| `issues` opened, reopened, or labeled | `inspect` | issue and repository context |
| daily schedule at `03:17 UTC` | `monitor` | every tracked path through inventory evidence |
| `workflow_dispatch` | selected by operator | complete repository inventory |
| `repository_dispatch` | event-specific | complete repository inventory |

Supported repository-dispatch types:

```text
amosclaud_pipeline
amosclaud_inspect
amosclaud_build
amosclaud_fix
amosclaud_deploy
amosclaud_monitor
```

### Repository scope

No tracked path is silently excluded from the trigger contract.

Push and pull-request runs send the changed-path manifest. Scheduled, manual, and repository-dispatch runs send:

- the complete tracked-file count;
- a SHA-256 digest of the sorted manifest;
- surface counts for current applications, legacy applications, GitHub-native applications, packages, services, web assets, infrastructure, tests, documentation, and unclassified paths;
- `excluded_paths: []`;
- explicit flags confirming that legacy and GitHub-native applications remain included.

This keeps large full-repository events bounded while still proving what inventory was considered.

### Required secrets

Configure these repository secrets when GitHub should send the event to a deployed Amosclaud control plane:

```text
AMOSCLAUD_PIPELINE_URL
AMOSCLAUD_GITHUB_PIPELINE_TOKEN
```

`AMOSCLAUD_PIPELINE_URL` is the public Amosclaud base URL, for example `https://www.amosclaud.com`.

`AMOSCLAUD_GITHUB_PIPELINE_TOKEN` is a dedicated random service token. Configure the identical value on the Amosclaud server. Do not reuse a GitHub personal access token, model key, billing secret, or user API key.

The server also needs an existing automation owner:

```text
AMOSCLAUD_GITHUB_AUTOMATION_USER_ID
```

or:

```text
AMOSCLAUD_GITHUB_AUTOMATION_EMAIL
```

When neither is set, the server attempts to use its first existing administrator. Production deployments should configure the owner explicitly.

### Truthful bridge behavior

For untrusted fork pull requests, secrets are normally unavailable. In that situation the workflow:

- creates `.amosclaud/evidence/github-native-event.json` locally;
- reports `evidence_only`;
- does not claim that a remote pipeline was created;
- allows the normal read-only pull-request checks to continue.

For non-pull-request events on `main`, the bridge is considered required. A configured endpoint failure is then surfaced as a workflow failure instead of being hidden.

### Deduplication

A push and pull-request event for the same repository and source commit use the same deterministic delivery identity. The server stores delivery IDs and returns the existing cooperation pipeline when the same event is received again.

Deduplication prevents two GitHub events for one source commit from creating two independent pipelines.

### Approval boundary

Automatic GitHub events always create pipelines with:

```json
{
  "allow_writes": false,
  "automatic_trigger": true
}
```

A requested `fix` or `deploy` therefore remains blocked at the normal protected-stage approval gate. The workflow does not merge pull requests, push directly to a protected default branch, deploy production, expose secrets, or delete external resources.

## Specialized workflows

The repository contains multiple established workflows for areas such as:

- Python versions and packaging;
- platform build verification;
- repository behavior and real-operation audits;
- Docker image validation;
- security and static analysis;
- live-server smoke checks;
- workspace compatibility;
- CI/CD verification.

These workflows remain independent because they have different tools, permissions, timeouts, and evidence. Their results can feed the shared Amosclaud ecosystem without being collapsed into one enormous workflow file.

The cooperation principle is:

```text
specialized workflow responsibility
        +
shared pipeline identity, event, artifact, and PipeFail evidence
        =
one ecosystem without disabling working services
```

## Manual dispatch

From the repository's **Actions** tab:

1. select **Amosclaud Native Pipeline**;
2. choose **Run workflow**;
3. choose `inspect`, `build`, `fix`, `deploy`, or `monitor`;
4. optionally enter an objective;
5. run it against the intended branch.

A manual `fix` or `deploy` selection still does not pre-approve repository writes or deployment.

## Repository dispatch example

A trusted external system can call GitHub's repository-dispatch API with a supported event type and client payload:

```json
{
  "event_type": "amosclaud_inspect",
  "client_payload": {
    "mode": "inspect",
    "objective": "Inspect the repository and return verified evidence"
  }
}
```

The caller must authenticate to GitHub with permission to create repository dispatches. That GitHub credential belongs to the caller and must never be committed to this repository.

## Failure evidence

When a workflow fails:

1. open the failed job;
2. identify the first failed command rather than relying only on the final summary;
3. download uploaded diagnostics when present;
4. attach sanitized evidence to the issue or pull request;
5. route retryable runtime failure through PipeFail rather than marking the original result successful.

Fast PR Gate failures upload `fast-pr-gate-diagnostics`. GitHub-native bridge evidence is written to `.amosclaud/evidence/github-native-event.json` during the run.

## Adding or modifying a workflow

A workflow pull request must explain:

- the event that triggers it;
- why an existing workflow cannot own the responsibility;
- the minimum required permissions;
- concurrency and cancellation behavior;
- timeout behavior;
- what evidence is produced on success and failure;
- how secrets are isolated;
- whether it changes approval, merge, or deployment policy;
- how it participates in the shared Amosclaud pipeline ecosystem.

Pin third-party actions to a full commit SHA. Do not grant write permissions to a job that only reads or verifies the repository.
