# Verified JSON autorepair

Amosclaud-Fixer now treats a narrow class of malformed JSON as safely repairable:

- line comments (`// ...`) outside strings;
- block comments (`/* ... */`) outside strings;
- trailing commas before `}` or `]` outside strings.

The implementation uses only Python's standard library, so no new runtime dependency or requirements-file entry is needed.

## Safety contract

1. Doctor first attempts strict JSON parsing.
2. When strict parsing fails, Amosclaud removes only comments and trailing commas outside quoted strings.
3. The normalized result must parse successfully before the finding becomes `REPAIRABLE`.
4. Fixer writes canonical JSON only for that proven-safe case.
5. Doctor reruns after the change.
6. Failed verification triggers the existing rollback path and no repair PR is published.
7. Ambiguous JSON remains `CRITICAL` and is never rewritten automatically.

This closes the `.codesandbox/tasks.json` failure shown by the autonomous repair report without weakening the rule that critical or unverified changes must not be published.
