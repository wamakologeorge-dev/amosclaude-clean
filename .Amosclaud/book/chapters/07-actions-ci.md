# Chapter 07 — Actions, CI and Verification

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Amosclaud uses automated checks to turn software changes into evidence. The repository contains GitHub workflows, pipeline services, verification and repair logic, build tooling, security checks and native Actions concepts. GitHub Actions remains part of the current repository operating path; a completely independent Amosclaud Actions infrastructure must only be marked verified when its own runners and control plane demonstrate that lifecycle.

Verification is broader than CI. A useful check says what was executed, against which revision and environment, and whether the observed result supports the claim being made. Skipped checks do not count as success. A merge does not prove deployment health. A deployment status does not prove the complete product works.

## Book Gate

The Amosclaud Word Book adds another engineering invariant: meaningful product changes must update the Book. Future merge workflows should run the Book gate alongside tests. The gate can establish that the Book changed and a report exists, but branch protection or Amosclaud policy must enforce that check before a merge operation is permitted.

Agents should report failing checks truthfully, repair only failures within their task authority, rerun the relevant verification and update the Book with the resulting evidence.

## True-result chain

A strong result can be traced from request → changed files → executed checks → logs/artifacts → verification state → Book report. That chain prepares both the next human and the next AI agent to continue without rediscovering the entire system.

**End of Chapter 07.**
