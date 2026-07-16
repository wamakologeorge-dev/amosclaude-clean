# Amosclaud Autonomous ReAct

The ReAct engine is a governed execution service beneath the single main
`AutonomousOrchestrator`. It does not create a second Autonomous agent.

## Cycle

1. Reason about the next bounded action.
2. Authorize the selected registered tool.
3. Act inside the controlled workspace.
4. Record a typed observation containing result evidence, not private reasoning.
5. Verify successful evidence before reporting completion.
6. Stop when blocked, verified, or the configured step limit is reached.

## Safety boundaries

- Read tools are allowed only when registered for the task.
- Write tools require explicit task authorization.
- File access remains constrained by `SafeFileManager`.
- Unknown tools are rejected.
- Tool exceptions become failed observations.
- Execution tasks cannot claim success without successful observations.
- Guidance tasks may finish without running repository verification.

## Activation

Existing engineering behavior remains the default while ReAct is introduced.
Callers activate ReAct with either:

- `mode="react"`, or
- task metadata containing `{"use_react": true}`.

All results still return through the main Amosclaud Autonomous entry point.
