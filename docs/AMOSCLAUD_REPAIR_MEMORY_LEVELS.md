# Amosclaud Repair Memory Levels

Amosclaud progresses from Level 1 to Level 5 only through new verified repair techniques.

- Level 1: diagnose safely.
- Level 2: one unique verified technique.
- Level 3: two unique verified techniques.
- Level 4: three unique verified techniques.
- Level 5: four or more unique verified techniques.

Repeating a known repair increases its reuse count but does not unlock another level. Failed, discarded, or unpublished repairs award no level.

## Storage

The authoritative Actions catalog is kept on the dedicated `amosclaud-memory` branch:

```text
Amosclaud-storage/repair-memory/catalog.json
```

Persistent installations can set:

```env
AMOSCLAUD_REPAIR_MEMORY_CATALOG=/data/amosclaud-storage/system/repair-memory/catalog.json
```

The catalog contains normalized problem signals, file types, verification names, source run identifiers, reuse counts, and level state. It does not contain old patches or executable repair code.

## Repair behavior

1. Doctor diagnoses the current repository.
2. Amosclaud Storage Memory is searched for a matching verified technique.
3. A match can prioritize a trusted Fixer handler or guide a new bounded candidate.
4. The current files are repaired; an old patch is never copied automatically.
5. Credential-free verification checks the new result.
6. Only a successfully published verified repair can update the Actions catalog.
7. A new technique unlocks one level. A repeated technique records reuse only.

`Amosclaud Repair Memory Learner` performs the catalog update after a successful repair-control run. The daily Autonomous workflow reads the same catalog and reports the current earned level.
