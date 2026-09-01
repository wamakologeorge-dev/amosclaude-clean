# Chapter 09 — Security and Identity

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Amosclaud security begins with identity and authority. A signed-in user, administrator, agent, connector, worker or model must not automatically receive every platform permission. The repository contains account/authentication code, administrator checks, API-key management, service-key routes, vault and access-policy concepts, organization identity and security middleware.

The platform should keep secrets out of Book content. The Book records that a credential or authorization mechanism exists, its scope and verification evidence where safe, but never stores passwords, private keys, bearer tokens or recoverable secrets in Git-tracked chapters or change reports.

Agent authority must be explicit. Reading the Book gives an agent context, not permission. Learning progress gives knowledge, not privilege. Workspace access does not imply deployment or merge authority. Connector installation does not imply organization ownership. High-impact operations must remain controlled by the platform's actual identity and policy systems.

For physical Amosclaud machines, identity must extend to the device: enrollment, machine credentials, secure storage, update trust, recovery and revocation. Those appliance-level guarantees remain part of the completion work and should not be marked verified before evidence exists.

## Book rule

Security changes must report affected policy boundaries, tests performed, safe evidence and known limitations. Sensitive values must be redacted or omitted.

**End of Chapter 09.**
