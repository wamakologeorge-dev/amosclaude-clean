# Amosclaud Self-Agent Programmer

The Amosclaud Self-Agent Programmer is the autonomous software-engineering execution layer of the Amosclaud platform.

## Mission

Its job is not merely to answer programming questions. Given sufficient user authority, workspace access, and execution capacity, it should be able to take a software objective from request to verified result.

```text
request → understand → inspect → plan → edit → execute → test → debug → repair → verify → deliver
```

## Core capabilities

The complete programmer contract covers:

- repository and project understanding;
- file creation and editing;
- terminal and process execution;
- dependency and environment inspection;
- build, test, lint and static-analysis execution;
- failure diagnosis and bounded repair;
- debugging;
- application and project scaffolding;
- documentation maintenance;
- Git status, diff and commit preparation;
- governed pull-request operations;
- deployment preparation and governed execution;
- logs, runtime evidence and monitoring;
- persistent project memory with evidence-aware learning;
- Amosclaud Programming Language support;
- SpaceCodeMe workspace collaboration.

## Authority model

Autonomy is not equivalent to unlimited privilege. The programmer receives an authority envelope from the platform. That envelope can include capabilities such as:

```text
workspace.read
workspace.write
terminal.execute
repository.commit
repository.push
repository.pull_request
network.outbound
deployment.execute
secrets.use
```

The runtime must reject operations outside the granted envelope. Sensitive values should remain isolated from model context whenever a brokered operation can perform the task without exposing the value.

## Verification contract

The programmer must distinguish between four states:

- **planned** — a proposed approach exists;
- **changed** — files or configuration were modified;
- **executed** — relevant commands actually ran;
- **verified** — evidence demonstrates that the requested acceptance conditions were met.

It must not report `verified` merely because code was generated.

## Workspace model

SpaceCodeMe is the primary development-computer surface for the Self-Agent Programmer. The agent should be able to work with the same project state visible to the developer: repository files, changed files, terminal sessions, builds, tests, ports, problems, logs and execution evidence.

## Agent loop

A production agent loop should resemble:

```text
1. Receive objective and authority.
2. Resolve repository/workspace context.
3. Inspect relevant files and current state.
4. Build an executable plan.
5. Perform the smallest useful action.
6. Observe the real result.
7. Diagnose failures.
8. Repair when authorized.
9. Run acceptance verification.
10. Persist only trustworthy learning/evidence.
11. Return the real outcome and remaining blockers.
```

The loop should be bounded by time, resource, action, and retry budgets.

## Self-programming

"Self-Agent Programmer" does not mean uncontrolled self-modification. Amosclaud may improve Amosclaud source code when working in an authorized repository exactly as it would improve another project: through visible changes, tests, verification, policy, review, and deployment controls.

No self-generated change becomes trustworthy merely because Amosclaud authored it.

## Relationship to the Amosclaud language

The `.amos` language provides a future native way to express programs, automation and governed agent tasks. The Self-Agent Programmer should eventually understand, generate, test, debug and maintain `.amos` projects while continuing to work with existing languages.

## Definition of complete

The Self-Agent Programmer can be considered complete only when a developer can provide a non-trivial software objective and the system can consistently produce real workspace changes, execute the relevant toolchain, recover from common failures, provide verification evidence, respect permissions, and deliver the resulting artifact or repository operation without substituting a text-only answer for execution.
