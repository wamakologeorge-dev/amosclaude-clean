# Amosclaud Repair Memory Levels

Amosclaud progresses from Level 1 to Level 5 only through new verified repair techniques.

- Level 1: diagnose safely.
- Level 2: one unique verified technique.
- Level 3: two unique verified techniques.
- Level 4: three unique verified techniques.
- Level 5: four or more unique verified techniques.

Repeating a known repair increases its reuse count but does not unlock another level. Failed, discarded, unpublished, or partially verified repairs award no level. One verified learning event can unlock at most one new level.

## Storage authority

The production authority is the persistent Amosclaud Storage catalog:

```text
/data/amosclaud-storage/system/repair-memory/catalog.json
```

Configure it on Railway or another persistent deployment:

```env
AMOSCLAUD_REPAIR_MEMORY_CATALOG=/data/amosclaud-storage/system/repair-memory/catalog.json
AMOSCLAUD_MEMORY_ACCESS_KEY=<independent random service key>
AMOSCLAUD_MEMORY_API_URL=https://www.amosclaud.com
```

Create `AMOSCLAUD_MEMORY_ACCESS_KEY` as a Railway variable and a GitHub Actions repository secret using the same value. It is a service-to-service credential. Never put it in a browser, extension setting, installation package, model prompt, repository file, or Actions variable.

The dedicated `amosclaud-memory` branch is the sanitized Actions mirror:

```text
Amosclaud-storage/repair-memory/catalog.json
```

The catalog contains normalized problem signals, file types, verification names, source run identifiers, reuse counts, and level state. It does not contain credentials, complete logs, user data, source patches, executable repair code, or copied repository files.

## Repair behavior

1. Doctor diagnoses the current repository.
2. Amosclaud Storage Memory is searched for a matching verified technique.
3. A match can prioritize a trusted Fixer handler or guide a new bounded candidate.
4. The current files are repaired; an old patch is never copied automatically.
5. If the first repair is blocked, the workspace is cleaned and memory may guide one bounded retry.
6. Current credential-free checks re-verify the new result.
7. Only a successfully published verified repair can update memory.
8. A new technique unlocks one level. A repeated technique records reuse only.
9. A failed run records the failure count without changing the level.

## Daily workflow

`Amosclaud Daily Autonomous Orchestrator` runs once per day. It:

1. checks out `main`;
2. clones the `amosclaud-memory` branch;
3. refreshes the local catalog from the protected backend when available;
4. tries the canonical Amosclaud provider route;
5. uses the repository-owned Ollama route as a bounded fallback when the website API key is unavailable or revoked;
6. consults only verified declarative memory;
7. verifies the proposed change before opening a pull request;
8. records a new technique only after the required checks pass; and
9. writes the sanitized catalog back to the memory branch.

`Amosclaud Repair Memory Learner` also learns from a successful Repair Control Plane run only when its candidate, publication, credential-free verification, and evidence artifacts all pass.

## Shared consumers

The same `VerifiedRepairMemory` contract is used by:

- Amosclaud Autonomous;
- Doctor and Fixer;
- the decision engine;
- the Repair Control Plane;
- the daily agent; and
- trusted GitHub Actions.

No component receives a private copy of the knowledge model. All consumers retrieve the same sanitized techniques and must re-diagnose and re-verify the current code.
