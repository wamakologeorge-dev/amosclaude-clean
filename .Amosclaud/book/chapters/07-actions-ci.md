# Chapter 07 — Actions, CI and Verification

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Amosclaud uses automated checks to turn software changes into evidence. The repository contains GitHub workflows, pipeline services, verification and repair logic, build tooling, security checks and the native Amosclaud Action. GitHub Actions remains the execution host for this repository workflow, while the verification logic and policy belong to Amosclaud.

## Native Amosclaud Action

Every repository change that enters the Amosclaud-managed GitHub path must be sent through the native Amosclaud Action before it can be treated as verified. The Action runs Amosclaud's deterministic guardrails and the repository test suite, then publishes a machine-readable verification report as a workflow artifact.

The native Action is not a replacement for GitHub Actions. It is an Amosclaud-owned verification layer running natively inside GitHub Actions. This preserves GitHub Actions compatibility while giving Amosclaud its own test and verification contract.

Verification is broader than CI. A useful check says what was executed, against which revision and environment, and whether the observed result supports the claim being made. Skipped checks do not count as success. A merge does not prove deployment health. A deployment status does not prove the complete product works.

## Book Gate

The Amosclaud Word Book adds another engineering invariant: meaningful product changes must update the Book. The Book Gate runs alongside repository verification and blocks meaningful pull-request changes that do not update `.Amosclaud/book/`. The Book therefore receives the architectural change, implementation status, verification evidence and next task needed by the next human or AI agent.

## Permanent failure memory

A failed Book or verification result is itself engineering evidence and must not disappear when the mistake is corrected. The canonical `.Amosclaud/book/failures.jsonl` ledger records failures with a stable `failure_id`, related `change_id`, actor, expected state, actual state, Action result, correction, verification and lessons learned.

Failure records are append-only. A correction must never rewrite or delete the original failure; it creates a new record or completion entry that points back to the failure. This preserves the true history so future humans and agents can see what went wrong, how it was repaired and what rule should prevent the same mistake.

The intended chain is:

**Change → Book record → Amosclaud Action → FAIL → Failure Record → Correction → Amosclaud Action → PASS → Completion Record**

Agents should consult the Book before work, send the resulting change through the native Amosclaud Action, report failing checks truthfully, repair only failures within their task authority, rerun the relevant verification and record the resulting evidence in the Book.

## True-result chain

A strong result can be traced from request → Book context → changed files → native Amosclaud Action → executed checks → logs/artifacts → verification state → Book report. Failures are retained as permanent evidence rather than silently overwritten. No component should declare itself healthy merely because it produced a change.

**End of Chapter 07.**
