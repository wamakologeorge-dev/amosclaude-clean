# Amosclaud Postortores

**Status: 🚧 In progress**

Amosclaud Postortores is the native data-system contract for the Amosclaud ecosystem. It is designed to store more than ordinary relational rows: platform state, immutable history, agent memory, event streams, verification evidence, graph relationships and worker coordination are first-class data primitives.

## Why Postortores exists

PostgreSQL is an excellent relational database, but Amosclaud needs a product-level data contract that matches the way its agent, SpaceCodeMe, execution nodes, verification engine, applications and physical machines operate. Postortores owns that contract so higher Amosclaud layers do not depend on one external database product or one storage model.

The first implementation intentionally uses SQLite only as a bootstrap persistence substrate. That allows local and physical Amosclaud machines to run the native API without requiring a separate database server. SQLite is not the Postortores product contract, and the storage engine can later be replaced or distributed without changing the higher-level Amosclaud data model.

## Native primitives

Postortores v0 introduces:

- **Versioned state** — every write creates an immutable version rather than silently replacing history.
- **Append-only event streams** — agent, task, build and platform events retain ordered execution history.
- **Agent memory** — semantic/vector memory is part of the data system rather than a separate bolt-on database.
- **Verification evidence** — truth states (`planned`, `changed`, `executed`, `verified`, `blocked`, `failed`) and proof payloads are persistent records.
- **Graph relationships** — projects, repositories, users, agents, applications, machines and artifacts can be connected directly.
- **Worker leases** — execution nodes can coordinate ownership of workspaces or tasks through durable leases.
- **Content hashes** — important records carry deterministic SHA-256 evidence for integrity and later replication/audit work.

## What Postortores should eventually hold

The native data system is intended to become the persistence authority for:

- accounts, organizations and identity relationships;
- projects, repositories and workspace state;
- agent plans, tasks, memory and learning history;
- model metadata and model execution records;
- applications, connectors, API keys, tokens and authorization grants;
- build, test, debug, repair and deployment events;
- verification evidence and true-result records;
- artifacts, object metadata and content-addressed references;
- machine/node enrollment, heartbeats, leases and resource state;
- observability events, audit trails and policy decisions.

## Ecosystem position

```text
Amosclaud Web / Desktop / SpaceCodeMe
                |
        Amosclaud Platform API
                |
       Amosclaud Postortores
        /       |        \
 versioned    events     memory
 state        evidence    graph
                |
      bootstrap storage engine
             SQLite
                |
        future native/distributed
        Postortores storage engine
```

Postortores sits below the platform runtime and above physical persistence. Redis may continue to serve transient queue/cache workloads during migration, and existing SQL stores may remain compatibility sources until their data is migrated. New Amosclaud-native features should target the Postortores contract instead of adding new direct database dependencies.

## Current API

Python package: `postortores`

```python
from postortores import DataRecord, PostortoresEngine

engine = PostortoresEngine("/data/postortores.db")
engine.put(DataRecord("projects", "alpha", {"status": "active"}))
project = engine.get("projects", "alpha")
```

The initial engine provides `put`, `get`, `history`, `append_event`, `read_events`, `remember`, `search_memory`, `record_evidence`, `evidence_for`, `link`, `neighbors`, `acquire_lease` and `health`.

## Non-goals for v0

This first change does **not** claim that Postortores is already a production-scale replacement for PostgreSQL, MySQL, Redis, an object store, a distributed vector database or a replicated consensus system. It establishes the native Amosclaud data contract and a deterministic local persistence implementation that can be tested and evolved without locking the platform to a third-party database API.

## Roadmap

1. Integrate Postortores behind the canonical Amosclaud platform persistence layer.
2. Add authenticated REST/MCP interfaces and organization-aware policy enforcement.
3. Add content-addressed blob/artifact storage and snapshots.
4. Add encrypted secrets/value classes and field-level access policy.
5. Add replication, WAL shipping, backup/restore and point-in-time recovery.
6. Add distributed vector indexes and larger memory stores.
7. Add temporal queries, subscriptions/change feeds and offline sync for Amosclaud Desktop/physical machines.
8. Migrate existing platform records incrementally with dual-read/dual-write verification.
9. Replace the bootstrap substrate only after a native/distributed storage engine has equivalent durability evidence.

## Verification policy

Code in this branch is implementation evidence, not production proof. Postortores remains **🚧 In progress** until CI and end-to-end integration establish the relevant runtime evidence. A successful local database test does not prove distributed durability, replication or production migration safety.
