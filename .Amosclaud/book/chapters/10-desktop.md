# Chapter 10 — Amosclaud Desktop

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

Amosclaud Desktop is the local client and machine-facing experience for connecting a developer computer to Amosclaud services, workspaces, models and connectors. The repository contains desktop gateway and developer-client foundations, but the Book does not treat a fully packaged, universally verified desktop product as complete unless installation and end-to-end evidence demonstrate it.

Desktop should work with both local and remote Amosclaud services. In the long-term provider-independent path, a user can run the platform, model, SpaceCodeMe and Book locally or on an Amosclaud machine while the public website remains an optional control surface rather than a mandatory hop for every operation.

The Book is useful to Desktop because it can provide a compact offline orientation snapshot: current platform state, relevant chapters, capability truth, next task and the Book version the agent consumed. When connectivity returns, runtime changes can synchronize back through the same Amosclaud-native Book contract and then be represented in repository history when repository synchronization is enabled.

## Completion boundary

A complete Desktop claim requires packaging, installation/update behavior, authentication, workspace launch, model/agent connectivity, reconnect/recovery behavior and verified synchronization. Source code for a client is only implementation evidence.

## Book rule

Desktop changes must update this chapter when installation, connectivity, local execution, synchronization or user-facing behavior changes.

**End of Chapter 10.**
