# Chapter 02 — Amosclaud Platform

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

The Amosclaud Platform is the control and product layer that joins accounts, organizations, repositories, workspaces, agents, execution, APIs, storage, applications, connectors, metrics and deployment behavior. The canonical FastAPI runtime is in `amoscloud_ai`, while supporting packages and services provide specialized functions.

## Current repository foundation

The source tree contains a platform runtime, API gateway concepts, account/authentication routes, repository services, workspace services, execution and pipeline surfaces, model integration, MCP support, metrics, web clients, developer clients, deployment tooling and tests. Their presence is implementation evidence, not a guarantee that every route or deployment is currently healthy.

The platform's desired boundary is provider-independent: Amosclaud should own its product contracts while adapters connect to outside repositories, hosting systems, identity providers, models and third-party tools. External providers are integrations, not the definition of Amosclaud.

## Control flow

A normal engineering task should enter Amosclaud through a human UI, API, MCP client or connector. Identity and policy establish who may act. A task router chooses an execution path. The agent and model prepare work. SpaceCodeMe or another workspace supplies files and tools. Execution nodes build and test. Verification records evidence. Results and artifacts are retained and returned through the requesting interface.

## Book relationship

The Book is now part of the platform contract. Before changing a subsystem, an agent should query the Book for current capability status and next-task context, then inspect the real implementation. After a meaningful change, the agent must update the Book change ledger and relevant chapter/capability entries.

## Completion boundary

The platform is not called complete merely because routes exist. Completion requires an end-to-end verified lifecycle: install/start, identity, project creation, durable state, agent task execution, workspace provisioning, build, test, repair, re-test, true-result evidence, artifact retention, repository/release actions where requested, monitoring, recovery and successful restart.

**End of Chapter 02.**
