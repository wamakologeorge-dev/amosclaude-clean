# Amosclaud Architecture Contract

Status: **Authoritative**

This document defines the permanent product and backend architecture for Amosclaud. New work must comply with this contract before it is merged.

## Product boundary

Amosclaud exposes exactly three product areas:

1. **Autonomous**
2. **Repository**
3. **Results**

Users interact with one identity only: **Amosclaud Autonomous**.

Terms such as mini agent, cloud agent, assistant agent, repair agent, deployment agent, model agent, CI agent, doctor agent, mission-control agent, or worker agent must not be presented as separate user-facing agents. Internal modules may exist, but they are capabilities owned by the same Autonomous kernel.

## Canonical flow

```text
User
  |
  v
Amosclaud Autonomous
  |
  +-- Repository
  |     +-- inspect
  |     +-- create and edit files
  |     +-- branches and commits
  |     +-- pull requests
  |     +-- tests and CI
  |
  +-- Results
        +-- status
        +-- evidence
        +-- logs
        +-- test results
        +-- deployment result
        +-- artifacts and URLs
```

## Single composition root

`src.amosclaud_os.kernel.AutonomousKernel` is the canonical backend composition root.

All conversations, model calls, repository operations, repairs, tests, deployments, monitoring operations, background jobs, and result reporting must enter through this kernel or a thin adapter that calls it.

No module may construct a second autonomous brain, independent orchestration identity, or competing runtime.

## Capability rules

The one Autonomous may:

- create projects and files;
- inspect and modify repositories;
- diagnose and fix defects;
- run tests and CI checks;
- create branches, commits, and pull requests;
- deploy approved work;
- monitor services;
- return verified results.

Authorization controls govern whether a real write or external action is allowed. They must never be described as evidence that Autonomous is inherently unable to create, fix, test, or deploy.

## Repository contract

Repository operations must be explicit, bounded to the selected workspace or connected repository, and recorded in Results.

Every mutation result should identify, when available:

- repository;
- branch;
- changed files;
- commit SHA;
- pull-request URL;
- verification performed.

Generated files, cache files, compiled bytecode, local databases, secrets, and build artifacts must not be committed unless they are intentionally required source assets.

## Results contract

Results are truthful, structured, and evidence-backed.

A result must distinguish among:

- `planned`
- `running`
- `completed`
- `blocked`
- `failed`
- `cancelled`

A successful claim requires evidence. A failure must expose the exact known reason without inventing details.

The statement "do not fabricate results" means Amosclaud reports verified outcomes. It must not be used as wording that suggests Amosclaud cannot perform real work.

## API shape

The preferred public backend response has three top-level areas:

```json
{
  "autonomous": {
    "name": "Amosclaud Autonomous",
    "identity": "one-agent"
  },
  "repository": {
    "name": "selected repository",
    "workspace": "resolved workspace"
  },
  "results": {
    "status": "completed",
    "evidence": [],
    "logs": [],
    "tests": null,
    "deployment": null,
    "artifacts": []
  }
}
```

Legacy endpoints may remain temporarily for compatibility, but their implementation must delegate to the same kernel and return the same identity.

## Pull-request standard

Each architecture or runtime pull request must contain:

- one clear purpose;
- a bounded file set;
- an architecture impact statement;
- exact tests executed and their results;
- deployment or migration notes;
- known limitations;
- no unrelated generated artifacts;
- no unresolved competing-agent terminology.

Large unrelated feature collections must be split before review.

## Required tests

The backend test suite must verify:

1. only one public Autonomous identity exists;
2. all execution paths are stamped by the canonical kernel;
3. authorized repository writes can create and fix files;
4. test and deployment outcomes are represented in Results;
5. failed operations remain visible and truthful;
6. legacy routes cannot introduce a second agent identity.

## Review rule

A new capability is acceptable only when it can answer both questions:

1. How does this extend the existing `AutonomousKernel`?
2. Where does its verified output appear under Results?

If either answer is unclear, the change is not architecturally ready.
