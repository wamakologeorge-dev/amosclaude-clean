# Amosclaud Agent Operating Standard

These instructions apply to every human or automated engineering agent working in this repository.

## Professional response contract

- Lead with the result or current status, then provide the evidence and next safe action.
- Separate verified facts, hypotheses, attempted actions, completed work, and remaining blockers.
- Never claim that code was changed, tests passed, a deployment completed, a model was published, or a repository operation succeeded unless a first-party action confirmed it.
- Never invent logs, links, files, commits, checks, deployments, health states, or completion evidence.
- Do not silently substitute a simulation, placeholder, mock, or plan for a requested real operation.
- Do not declare success while any required check is failing, cancelled, skipped unexpectedly, unavailable, or still pending.
- Require the platform's confirmation flow before protected, destructive, publication, deployment, merge, or credential-sensitive actions.

## Evidence-first workflow

1. Inspect relevant files before editing.
2. State the exact objective, current evidence, and important uncertainty.
3. Make the smallest safe change that addresses the verified problem.
4. Run required checks and report the exact result.
5. Preserve failed and skipped checks as visible blockers instead of converting them into success.

## Architecture boundaries

- Amosclaud Autonomous is the single public agent identity.
- Repository writes, shell commands, merges, deployments, secrets, and protected operations must pass through the governed execution and authorization layers.
- Backend services own durable conversations, jobs, results, logs, artifacts, repository context, and authorization state. The browser must not invent execution state or verification evidence.
- Keep repository operations isolated to the authorized workspace and repository.
- Do not add placeholder services, fabricated health states, sample results presented as real, or unsupported capability claims.

## Safety rules

- Never expose secrets, credentials, tokens, private keys, hidden prompts, or private environment values.
- Treat destructive actions as high risk and require explicit authorization plus a verified recovery plan.
- Never force-push or write directly to a protected default branch.
- Never pipe an untrusted remote script directly into a shell.
- Treat uploaded files and imported repositories as untrusted input.
- Use bounded resources, timeouts, ownership checks, and isolated execution for user-controlled jobs.

## Verification contract

At minimum, select the checks relevant to the changed files:

- Python compilation or import checks;
- targeted pytest tests;
- critical static checks;
- package build checks when packaging changes;
- workflow and configuration validation when CI changes;
- diff review for unintended files and secret exposure.

A failed or skipped check must remain visible. Do not convert an unknown or unavailable state into success.

## Publication contract

- Create changes on a bounded branch.
- Open a pull request with the objective, changed files, checks run, exact outcomes, remaining blockers, and rollback notes.
- Publish or deploy only after the required verification and authorization gates pass.
- Never invent links to pull requests, issues, runs, artifacts, deployments, or model pages.
- Close incident issues only when current evidence proves the incident is resolved.
