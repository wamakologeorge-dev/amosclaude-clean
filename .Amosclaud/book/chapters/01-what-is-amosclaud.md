# Chapter 01 — What Amosclaud Is

**Reading target:** 3 minutes  
**Audience:** Human + AI agent  
**Truth rule:** This chapter separates implemented capability from intended capability.

Amosclaud is an autonomous software-programming platform whose intended operating loop is to understand a software task, prepare a workspace, change real code, execute it, test it, diagnose failures, repair them, verify the result, preserve evidence, and return a true result to the person or system that requested the work.

The repository is not only a website. It contains the platform runtime, agent services, developer workspace foundations, repository automation, execution and verification systems, APIs, model integration, MCP integration, clients, deployment tooling, storage adapters, documentation, and tests. Some parts are mature; others remain under active construction. The Book must never turn planned work into a claim that it already works.

## The four primary layers

1. **Amosclaud Programming Language** — the Amosclaud-native language and command surface. The language project exists, but the complete language vision is still being built.
2. **Self-Agent Programmer** — the autonomous engineering layer that receives work, plans within an authority boundary, modifies software, executes tools, and gathers verification evidence. This is an active system and not yet a universal guarantee for every task.
3. **SpaceCodeMe** — the developer workspace layer for files, editor, terminal, ports, debugging, execution and agent-assisted work. Repository foundations exist; complete product verification is ongoing.
4. **Control Plane** — identity, projects, repositories, task routing, workers, applications, connectors, APIs, deployment, metrics, policy and coordination.

## What the Book is

The Amosclaud Word Book is the shared memory and navigation layer for humans and agents. Git keeps its portable representation with the source code. Amosclaud reads the same representation through a native Book service and API. Later, direct Amosclaud connections can update the same contract without making GitHub the only source of truth.

Every agent should begin by reading the current Book status and the chapters relevant to its task. Every meaningful implementation change must create a Book change report that says what changed, where it changed, what was tested, what was verified, what remains uncertain, and which chapters or capabilities were updated.

## Truth states

- **verified** — observed evidence demonstrates the stated capability.
- **implemented_verification_pending** — implementation exists but required verification has not completed.
- **in_progress** — active construction is incomplete.
- **planned** — accepted direction with no complete implementation yet.
- **blocked** — known dependency or failure prevents completion.
- **not_available** — the capability is not currently available.

A commit, PR, deployment, or merge is never by itself proof that a product works in production.

## How an agent should start

Read `/api/v1/book/status`, then `/api/v1/book/agent-context`. Read this chapter and the product chapter related to the requested work. Inspect the actual source and tests before changing anything. After work, append a Book change report and run the Book gate. Work is not eligible for completion when the gate says the Book is stale.

## Chapter completion

A human reader can mark this chapter finished through the Book API. An agent can also record that it consumed this chapter in its versioned context snapshot. Reading completion is orientation evidence, not engineering verification.

**End of Chapter 01.**
