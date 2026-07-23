# Amosclaud AI Verified Repair

**Amosclaud AI Verified Repair** is a safety-first repair workflow that detects a supported problem, applies the smallest safe correction, and proves that the result works before the repair is accepted or published.

A generated change is **not** considered successful merely because a file was modified. Amosclaud must validate the repaired file, rerun the relevant diagnostic checks, and reject or roll back any change that cannot be verified.

## Current capability: verified JSON autorepair

Amosclaud-Fixer currently treats a narrow, well-defined class of malformed JSON as safely repairable:

- line comments (`// ...`) outside quoted strings;
- block comments (`/* ... */`) outside quoted strings;
- trailing commas before `}` or `]` outside quoted strings.

The implementation uses only Python's standard library. It does not require a new runtime dependency or a requirements-file change.

## Verified repair lifecycle

Every automatic repair follows this sequence:

1. **Detect** — Doctor runs strict JSON parsing and records the original failure.
2. **Classify** — Amosclaud determines whether the failure matches a supported, deterministic repair pattern.
3. **Protect** — The original file state is preserved for comparison and rollback.
4. **Repair minimally** — Only supported comments and trailing commas outside quoted strings are removed.
5. **Parse again** — The normalized content must pass strict JSON parsing.
6. **Write canonically** — Fixer writes valid, consistently formatted JSON only after successful parsing.
7. **Verify independently** — Doctor reruns against the repaired repository state.
8. **Accept or roll back** — The repair is accepted only when all required verification checks pass. Otherwise, Amosclaud restores the original state.
9. **Publish evidence** — A repair PR or success result must include the detected problem, changed file, verification outcome, and checks executed.

## Safety contract

Amosclaud AI Verified Repair guarantees that:

- strict parsing is attempted before any normalization;
- transformations never modify comment-like text or commas inside quoted strings;
- only explicitly supported JSON defects are repaired automatically;
- a normalized result must parse successfully before it is classified as `REPAIRABLE`;
- verification is performed after the file is written, not only against an in-memory candidate;
- failed verification activates rollback and prevents publication of a repair PR;
- ambiguous, destructive, or unsupported changes remain `CRITICAL` and require human review;
- Amosclaud never reports `VERIFIED` without recorded verification evidence.

## Verification result states

| State | Meaning | Automatic publication |
|---|---|---|
| `DETECTED` | A problem was found but has not been repaired. | No |
| `REPAIRABLE` | The problem matches a supported deterministic repair rule. | No |
| `REPAIRED` | A candidate repair was written successfully. | No |
| `VERIFIED` | Post-repair diagnostics passed and evidence was recorded. | Yes, when repository policy allows it |
| `ROLLED_BACK` | Verification failed and the original state was restored. | No |
| `CRITICAL` | The problem is ambiguous, unsafe, or unsupported. | No |

## Example

### Invalid input

```jsonc
{
  // Development task configuration
  "tasks": [
    "test",
    "deploy",
  ],
}
```

### Verified output

```json
{
  "tasks": [
    "test",
    "deploy"
  ]
}
```

Amosclaud accepts this repair only after strict parsing and the required Doctor checks succeed on the written file.

## What Amosclaud will not repair automatically

Amosclaud does not guess missing values, rename unknown keys, merge duplicate keys, infer intended data types, reconstruct truncated files, or rewrite structurally ambiguous JSON. Those cases remain blocked for human review.

## Audit evidence

A verified repair report should record:

- repository and file path;
- original diagnostic or parser error;
- repair rule applied;
- before-and-after content hash;
- verification commands or checks executed;
- verification status;
- rollback status, when applicable;
- commit or pull-request reference, when published.

## Outcome

This verified repair flow resolves the `.codesandbox/tasks.json` malformed-JSON failure while preserving Amosclaud's central rule:

> **No repair is trusted until the repaired repository proves that it works.**
