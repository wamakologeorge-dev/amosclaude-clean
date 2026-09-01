# Chapter 08 — Applications and Connectors

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Applications and Connectors are the boundary between Amosclaud and external systems. The platform is intended to let a developer or organization authorize an Amosclaud application, choose permissions, issue scoped credentials, and allow approved tools or agents to exchange tasks and results without handing over unrestricted platform authority.

The repository contains integration settings, API-key services, repository integrations, provider APIs, webhooks, MCP support and developer-client foundations. These pieces show an active integration architecture. The Book must still distinguish individual implemented surfaces from a universal third-party application marketplace or fully provider-independent connector system.

A connector should know which organization, project and actor it represents, what operations it may request, how long its authorization lasts, and where evidence is returned. Credentials should be scoped and revocable. External systems should never become an implicit source of Amosclaud founder or administrator authority.

The Amosclaud Word Book itself follows the same portability principle. GitHub can version the Book files now, while the Amosclaud runtime reads and writes the same contract. Later direct MCP or Amosclaud connections can consume Book context without requiring GitHub to remain in the execution path.

## Book rule

Any new application, integration, connector, token scope or provider boundary must update the relevant capability record and this chapter when architecture or user-visible behavior changes.

**End of Chapter 08.**
