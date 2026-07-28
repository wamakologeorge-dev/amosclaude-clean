# Amosclaud System Core

The System Core is the authoritative registry for Amosclaud doctor capacity,
component policy capacity, repository inventory coverage, and CPU execution
limits.

## Doctor topology

| Component | Independent doctor lanes |
|---|---:|
| `amosclaud-clean` | 1 |
| `amosclaud-fixer` | 2 |
| `amosclaud-action` | 3 |
| `amosclaud-autonomous` | 4 |
| `amosclaud-security` | 3 |
| `amosclaud-codex-agent` | 10 |
| **Total** | **23** |

Each doctor receives a stable unique identifier. When one doctor is marked
unhealthy, the scheduler selects the next healthy sibling for that component.
If every sibling is unhealthy, the operation fails closed instead of claiming
that a repair succeeded.

## Component policy topology

| Component | Policy slots |
|---|---:|
| `amosclaud-fixer` | 12 |
| `amosclaud-action` | 11 |
| `amosclaud-autonomous` | 25 |
| `amosclaud-ai-agent` | 13 |
| `amosclaud-api-key` | 50 |
| **Total** | **111** |

Every registered component also inherits the System Core baseline policy. This
provides 100 percent system-policy coverage without inventing additional
component-specific policy counts that were not defined by the owner.

## Requirements, files, and tools coverage

`InventoryManifest` records the expected requirements, repository files, and
tools and compares them with the discovered inventory. `validate()` refuses to
mark the core ready while any required item is missing. A complete inventory
reports 100 percent coverage.

The inventory contract is evidence based: an item counts as covered only after
it has been recorded by the caller performing the repository or runtime scan.

## CPU policy

The initial System Core is limited to:

- one logical CPU core;
- one active doctor lane;
- a 100 percent utilization ceiling for that one core.

The 100 percent value is a maximum allowed budget, not a command to keep the
CPU permanently saturated. Doctor execution is serialized with a process-local
lock. A second non-waiting request receives `CoreBusyError` rather than running
in parallel.

## Safety properties

- Exact doctor and policy counts are immutable and validated at startup.
- Missing or extra doctor and policy slots fail closed.
- Doctor and policy identifiers must be unique.
- A failed doctor can be removed from rotation and restored explicitly.
- No component can bypass the System Core baseline policy.
- No second doctor can consume the single execution lane concurrently.
- Inventory readiness requires complete requirements, file, and tool evidence.

## Current boundary

This change establishes the central registry and scheduler contract. Existing
Doctor, Fixer, Action, Autonomous, Security, and Codex execution adapters must
be connected to this registry in bounded follow-up changes. The registry does
not by itself grant repository writes, deployment rights, secret access, merge
rights, or production authority.
