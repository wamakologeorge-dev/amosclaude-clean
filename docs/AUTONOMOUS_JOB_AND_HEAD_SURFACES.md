# Autonomous Job and Head-Surface Contract

This contract extends the Amosclaud architecture without creating another agent.

## Four canonical head files

The four head surfaces are:

1. `index.html` — root landing head.
2. `web/index.html` — authenticated Autonomous application head.
3. `public/index.html` — static or packaged public head.
4. `src/amoscloud_ai/templates/index.html` — server-rendered application head.

All four must expose the same identity and product structure:

- Amosclaud Autonomous
- Repository
- Results
- the active job and its current state

They may use different layouts, but they must not introduce separate agent names. Repository pages must link to the same Autonomous conversation and preserve the selected repository, user, permissions, job, progress, and evidence.

## Canonical job flow

```text
User
  |
  v
Amosclaud Autonomous
  |
  v
Jobs
  |
  +-- Repository
  |     +-- instructions
  |     +-- source and branches
  |     +-- create and edit
  |     +-- tests and CI
  |     +-- commit and pull request
  |
  +-- Results
        +-- status
        +-- evidence
        +-- work proof
        +-- tests
        +-- deployment
        +-- final location
        +-- usage instructions
```

## Ten job responsibilities

### 1. Read full repository instructions

Before planning or changing a repository, Autonomous reads all applicable repository instructions, scoped instructions, contribution rules, workflow requirements, and relevant documentation. Results record which instructions were applied.

### 2. Follow chat-assistant instructions

The same Autonomous keeps the agreed brief, asks only necessary questions, remembers answers, and turns the confirmed conversation into a job.

### 3. Remain the same Autonomous everywhere

The Autonomous available from Repository is the same one available in the main chat. Repository may include an `Ask Autonomous` control, but it must not create another assistant, reset the conversation unnecessarily, or force the user to leave the dashboard merely to ask a question.

### 4. Create and execute jobs with owner permissions

Read-only inspection may run without write permission. Repository creation, modification, commit, deployment, or another external action requires the connected user's applicable permission and explicit authorization.

### 5. Build a repository from start to finish

A Create or Build Repository button starts one governed job. The same Autonomous carries it through requirements, planning, repository creation, implementation, tests, commit or pull request, deployment when requested, and final verification.

### 6. Show Results evidence

Every job exposes real status, evidence, changed files, commits, tests, deployments, artifacts, URLs, failures, and blockers.

### 7. Show work proof

Proof can include diffs, paths, commit SHAs, pull-request links, test output, deployment logs, screenshots, checksums, health checks, and public endpoint verification.

### 8. Show the final result and how to use it

Completion identifies what changed, where to find it, how to run or open it, required configuration without revealing secrets, and any remaining limitations.

### 9. Track important daily learning

Autonomous may record useful learning from completed work, failures, corrections, repository patterns, test outcomes, and approved user preferences. Learning must be scoped, auditable, privacy-aware, and secret-free.

### 10. Test learning before activating it

Recorded learning is converted into a reproducible test, evaluation, rule check, or benchmark. It becomes active only after demonstrating improvement without breaking required behavior. Failed experiments remain visible in Results.

## Required public result fields

```json
{
  "autonomous": {
    "name": "Amosclaud Autonomous",
    "identity": "one-agent",
    "job_id": "job identifier"
  },
  "repository": {
    "name": "selected repository",
    "workspace": "resolved workspace",
    "permissions": "verified permission summary"
  },
  "results": {
    "status": "completed",
    "evidence": [],
    "work_proof": [],
    "logs": [],
    "tests": null,
    "deployment": null,
    "artifacts": [],
    "final_location": null,
    "usage_instructions": []
  }
}
```

## Required tests

Tests must prove that:

1. all four head files show Autonomous, Repository, and Results consistently;
2. Repository asks the same Autonomous without losing context;
3. permissions are checked before writes or deployments;
4. a create/build job can travel from button to verified final result;
5. Results include evidence and work proof;
6. final location and usage instructions are returned;
7. learning cannot become active without a passing test.
