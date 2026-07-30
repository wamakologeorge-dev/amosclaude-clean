# Amosclaud Atomic Tasks

Amosclaud atomic tasks are small, single-responsibility building blocks that prepare bounded instructions for the existing Amosclaud Autonomous runtime.

They do not create a second agent, execute arbitrary callables as trusted deployment code, or bypass repository authorization. Each atom declares its required context and permitted Autonomous modes. `run_autonomous_sequence` then sends the prepared instruction through `src.amosclaud_os.kernel.AutonomousKernel`, where planning, signed write authorization, execution, verification, and evidence reporting remain centralized.

## Structure

- `AtomicInstruction` defines the objective, Autonomous mode, and bounded metadata.
- `AtomicTask` validates one reusable task definition and its required context.
- `AtomicTaskRegistry` exposes trusted code-defined atoms for discovery and composition.
- `run_autonomous_sequence` delegates an atom to the canonical Autonomous kernel.

## Example

```python
from amoscloud_ai.atomic_tasks import docker_build_atom, run_autonomous_sequence

result = run_autonomous_sequence(
    docker_build_atom,
    {"path": "./amosclaud-clean"},
)
```

The Docker build atom requests a governed `build` operation. It does not report success or fabricate an artifact itself. The Autonomous runtime must return the real status, evidence, and artifacts. Write-capable execution remains blocked unless the normal Amosclaud security chain authorizes it.

## Composition

A molecule can select several registered atoms, prepare them in order, and pass each instruction through the same kernel. Shared state should be explicit dictionary data, artifact references, or approved Vault parameters rather than unrestricted global mutation.
