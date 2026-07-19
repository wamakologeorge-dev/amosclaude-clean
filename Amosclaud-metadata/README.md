# Amosclaud-metadata

`Amosclaud-metadata` is the canonical engineering-memory and provenance system for Amosclaud OS.

It records verified facts about repositories, commits, Autonomous missions, pipelines, deployments, repairs, learning outcomes, runtime health, services, models, and administrator-visible evidence.

## Authority

- **System head:** Amosclaud Autonomous
- **Operating system:** Amosclaud OS
- **Metadata source:** `Amosclaud-metadata/manifest.json`
- **Storage boundary:** the configured Amosclaud workspace only
- **Trust rule:** unverified claims must never be promoted to verified metadata

## Structure

```text
Amosclaud-metadata/
├── manifest.json
├── schemas/
│   └── metadata.schema.json
├── src/amosclaud_metadata/
│   ├── __init__.py
│   ├── models.py
│   ├── store.py
│   └── git_metadata.py
└── tests/
    └── test_metadata.py
```

## Record lifecycle

```text
observed -> pending_verification -> verified -> archived
                         \-> failed
```

Every record carries an immutable identifier, timestamp, source, verification state, evidence references, and optional links to commits, pipelines, deployments, repairs, and lessons.

## Safety rules

1. Never store passwords, access tokens, private keys, passkeys, session cookies, or raw environment secrets.
2. Never mark a result verified without evidence.
3. Preserve append-only history for completed missions and deployments.
4. Use atomic writes and deterministic JSON serialization.
5. Keep all paths inside the configured metadata root.
6. Amosclaud Autonomous coordinates writes; specialized services may only submit bounded records.
