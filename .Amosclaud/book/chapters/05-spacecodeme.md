# Chapter 05 — SpaceCodeMe

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

SpaceCodeMe is Amosclaud's software workspace. Its target experience combines repository files, editor behavior, terminal execution, ports, debugging, problems, agent assistance and isolated runtime tools so a developer or agent can build real software without depending on a fully configured local workstation.

The repository contains browser-workspace and terminal foundations, workspace control services, repository context, execution tooling and developer-facing web/client code. These are meaningful implementation foundations. The Book currently treats the complete SpaceCodeMe product as verification-pending rather than claiming every workflow is finished.

For agents, SpaceCodeMe should be the controlled place where code changes become executable evidence. The agent selects the correct project, inspects files, edits only within its authority envelope, runs builds/tests, captures output and passes results to verification. Workspace state must not be confused with durable platform state; persistent product records belong behind Amosclaud data contracts such as Postortores as that system matures.

A physical Amosclaud machine should be able to provision SpaceCodeMe locally, restore workspaces after restart and expose its workspace through approved clients without requiring GitHub or the public website for every operation.

## Book rule

Changes to editor, terminal, workspace provisioning, project context, ports, debugging or execution must be reported here or in the relevant capability entry before completion.

**End of Chapter 05.**
