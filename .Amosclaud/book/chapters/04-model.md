# Chapter 04 — Amosclaud Model

**Reading target:** 3 minutes  
**Audience:** Human + AI agent

The Amosclaud Model layer supplies reasoning and code-generation capability to the platform. The repository contains model routing, provider integration, model-network concepts, compatibility APIs and dedicated model packages. The architecture allows a task to use a configured Amosclaud model service while keeping the surrounding agent, workspace, execution and verification contracts owned by Amosclaud.

A model response is never automatically a verified engineering result. The Self-Agent Programmer must treat model output as a proposal until execution and verification provide evidence. This separation is essential because Amosclaud's product promise depends on true results rather than confident text.

The long-term machine design also requires the model layer to start reliably, advertise readiness, recover after restart, work with local execution resources and expose bounded health information. A physical Amosclaud machine should be able to run an appropriate local model route without making the public website mandatory for basic engineering work.

## Book rule

Changes to model selection, routing, prompts, tool contracts, model metadata or execution behavior must update this chapter or its capability record and add a Book change report. Evidence must identify whether only configuration exists or a model route was actually reached and used successfully.

**End of Chapter 04.**
