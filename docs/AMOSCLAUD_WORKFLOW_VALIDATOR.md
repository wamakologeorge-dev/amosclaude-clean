# Amosclaud Workflow Validator

`AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1`

## The blind spot this closes

When GitHub cannot load a workflow file, it does not fail a step. It refuses
the file. The run appears in the Actions list with **zero jobs, no logs, and no
annotations**, so nothing in CI reports a problem. A test suite cannot see it,
because the file never reaches a runner.

This repository ran that way for a long time. `amosclaud-repair-control-plane.yml`
accumulated **2,325 runs, zero successes, and zero jobs executed**. The cause was
one line: the workflow listed its own name among the workflows it waited on, and
GitHub voids the entire file with *"cannot listen to itself."* The autonomous
repair loop was fully built and correct. It was never allowed to start.

A repository-wide audit found **nine** workflows in this state.

## What it checks

| Code | Defect | Why GitHub refuses it |
|---|---|---|
| `AWV001` | YAML syntax error | The file cannot be parsed |
| `AWV002` | No `jobs:` key | Not a workflow (for example a conda or Render file left in the workflows directory) |
| `AWV003` | Workflow listens to itself | *"Workflow 'X' cannot listen to itself"* |
| `AWV004` | Context used where it does not exist | *"Unrecognized named-value"* — for example `runner.*` in a job-level `env:`, which is evaluated before a runner exists |
| `AWV005` | Calls a workflow that is itself invalid | The caller inherits the failure |
| `AWV006` | No `on:` trigger | The workflow can never run |

Only contexts GitHub actually recognises are inspected, so function calls such as
`hashFiles(...)` and `fromJSON(...)` are never mistaken for defects. Every rule
was derived from a real rejection observed on this repository.

## Use it

```bash
python scripts/ci/workflow_validator_guard.py
```

Exit code `0` means every workflow is one GitHub can load. Exit code `1` prints
each defect as `path:line: CODE message`.

It runs automatically in **Fast PR Gate**, so a workflow GitHub would reject is
caught on the pull request rather than after merge.

## Why it is first-party

An external linter parses these files without complaint: the defects are
GitHub-semantic, not syntactic. Amosclaud owns this check so the platform can
detect its own broken automation without depending on a third-party tool, in
line with the contributor tool policy.

## Ahead of GitHub

`fixer.yml` and `plan.yml` are triggered only by `workflow_dispatch`. Because
nobody had run them, GitHub had never evaluated them and still listed them as
healthy. Both were broken and would have failed the moment someone pressed
"Run workflow". The validator reports defects on every file, whether or not it
has ever been triggered.
