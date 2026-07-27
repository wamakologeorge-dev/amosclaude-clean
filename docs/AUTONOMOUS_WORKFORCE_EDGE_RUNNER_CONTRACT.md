# Autonomous Workforce Edge Runner Contract

An Amosclaud private runner must not receive engineering work merely because it is online. It must explicitly advertise the workforce protocol and the requested operation capability.

## Required heartbeat capabilities

```json
{
  "capabilities": [
    "engineering_workforce_v1",
    "build",
    "fix",
    "test",
    "review"
  ]
}
```

The runner may advertise only the modes it actually supports. `all` is accepted only for a runner intentionally configured for every workforce mode.

A model-only station that advertises inference capabilities is not eligible for repository execution.

## Execution requirements

An edge workforce runner is responsible for implementing the existing Global Task Router claim and completion protocol while preserving these boundaries:

- execute only the claimed repository and task;
- use an isolated container or microVM for untrusted repository commands;
- never expose the runner credential, GitHub credential, model token, or platform secrets to the project process;
- persist no credential in Git configuration or repository files;
- enforce CPU, memory, PID, filesystem, command-time, and network policy;
- create only the branch supplied by the workforce task;
- never force-push;
- never push directly to a protected branch;
- run deterministic verification before reporting completion;
- include a verification identifier and evidence with every completed task;
- report an exact blocker or failure instead of manufacturing success;
- stop when the task is cancelled or the runner credential is revoked.

## Scheduler behavior

`execution_preference=auto` selects the first eligible online edge runner. When no runner satisfies the contract, Amosclaud selects the controlled cloud/GitHub lane.

`execution_preference=edge` fails closed when no eligible runner is available. It does not silently execute on the public application process.

## Security note

The heartbeat capability is an eligibility declaration, not proof of isolation. Production deployments should attest runner version, image identity, isolation policy, and supported toolchain before enabling `engineering_workforce_v1` on a runner.
