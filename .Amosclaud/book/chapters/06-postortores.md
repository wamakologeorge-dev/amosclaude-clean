# Chapter 06 — Postortores Data System

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Postortores is the planned Amosclaud-native persistent data and state product. It is intended to own the platform contract for versioned state, events, agent memory, verification evidence, relationships, coordination, artifacts, backup/recovery and later distributed/offline behavior instead of forcing every Amosclaud product to depend directly on a particular third-party database.

At the time this chapter is established, Postortores is **in progress** and must not be described as a verified main-branch production database. Development work has explored a native contract and bootstrap storage, but the Book deliberately separates that work from what is currently verified on `main`.

The intended ownership includes accounts and organizations, projects and workspaces, agent tasks and memory, model execution metadata, applications and connectors, keys and authorization grants, build/test/repair events, true-result evidence, artifacts, machine enrollment and health, audit records and policy decisions.

Postortores may use lower-level storage engines during transition. Those engines are implementation substrates, not the product identity. The Amosclaud-native API, schema semantics, permissions, migrations, evidence, backup/restore and synchronization behavior define Postortores.

## Completion boundary

Production readiness requires durability evidence, authorization integration, migration of existing records, backup/restore and point-in-time recovery, replication/failure behavior, larger memory/vector workloads, offline synchronization and verified platform wiring.

## Book rule

Any Postortores implementation must update this chapter and capability status with exact evidence. A branch, commit, PR or schema file alone is not production proof.

**End of Chapter 06.**
