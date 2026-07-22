# Doctor healing coordinator

Doctor is the final verification authority, but it is no longer a first-failure stop switch.

For an autonomous repair run, Amosclaud now:

1. diagnoses the current repair scope;
2. selects one evidence-backed low-risk repair;
3. keeps that change in an isolated healing session;
4. re-diagnoses and selects the next distinct safe repair;
5. repeats within the configured attempt limit;
6. runs Doctor verification after the safe strategies have had a chance to heal the scope;
7. publishes only when verification passes;
8. rolls back the complete healing session when verification fails.

When no safe deterministic strategy is available, Doctor returns structured capability requirements containing the finding, affected path, next strategy, confidence, reason, and whether human approval is required. This makes a failure actionable without weakening truthful verification.

Doctor still blocks publication for unsafe or unverified changes. It does not block Amosclaud from trying additional registered safe healing strategies first.
