# Slapface — The Opening Page of the Amosclaud Book

**Audience:** founders, developers, operators, contributors, applications, and AI agents  
**Purpose:** vision, orientation, engineering guidance, continuity, and truth before work begins

Slapface is the first page of the Amosclaud Book. It is public project guidance, not a private agent tool.

Think of the Amosclaud Book as a living combination of a strong `README.md`, a small Word-style handbook, product documentation, engineering guidelines, project memory, and the canonical vision of what Amosclaud is becoming. A human developer should be able to open it and understand the platform. An AI agent should be able to read the same Book and understand what it must preserve before changing the platform.

## Amosclaud's North Star

Amosclaud is being built as an independent software-programming provider and computing platform — not only a chatbot, GitHub bot, coding assistant, or website.

The intended experience is simple:

**Idea → Requirements → Plan → Code → Files → Terminal → Build → Test → Debug → Repair → Security → Review → Application → Deployment → Monitoring → Maintenance → Improvement**

A person, developer, company, application, or authorized AI agent should be able to ask Amosclaud to build or repair software and receive a real result with evidence.

## The Project Is Bigger Than a Repository

In the Amosclaud vision, a project is the center of the developer experience. A project can contain:

- its repository and version history;
- a SpaceCodeMe workspace with files, editor, terminal, runtime, containers, debugger, and preview;
- Amosclaud Autonomous conversations and engineering tasks;
- applications and integrations;
- actions, runners, tests, security checks, and verification evidence;
- deployments, domains, databases, storage, logs, monitoring, and operational history;
- project memory and organization permissions.

GitHub, Railway, external model providers, and other services can be integrations. They must not become the identity or permanent foundation of Amosclaud.

## One Amosclaud Autonomous

Amosclaud Autonomous is the public engineering-agent identity. It should understand the objective, inspect the current project, plan within the granted authority, make controlled changes, execute tools, observe results, repair failures, and report evidence.

Different internal services can help it, but users should not have to manage a collection of unrelated public agents to complete one software task.

## Claim Is Not Evidence

The Book follows a strict truth rule:

- `planned` means a plan exists;
- `changed` means files or configuration were modified;
- `executed` means a relevant command or operation actually ran;
- `verified` means evidence proves the required result;
- `blocked` means a required condition prevents safe continuation;
- `failed` means the attempted result did not succeed.

"Tests passed" must point to a real test execution. "Deployment succeeded" must point to deployment and health evidence. "Complete" must never mean only that code was written.

## The Slapface Continuity Rule

The Book must also remember unfinished engineering work.

If an agent stops before finishing an important chapter of work, it records a Slapface handoff with:

- the last relevant Book chapter;
- a direct link to that chapter;
- the next line or task that was left unfinished;
- the risk of continuing too early;
- the missing pieces required to make the next step safe;
- an identifier for the unfinished handoff.

Before normal governed repository work begins, Amosclaud checks that handoff. If it is unresolved, the next agent must tell the account owner what Slapface found and return to the linked chapter.

An owner's request to "ignore it and continue" does not erase the engineering dependency. The only permitted path is to repair the missing pieces, verify the repair, record the evidence in the Book, resolve the handoff, and then resume the original objective.

## High-Confidence Secret Protection

Slapface also protects the Book and repository from accidental credential exposure, but it must not overreact.

A hard block requires high-confidence evidence. Examples include a realistic provider credential format or several signals agreeing at once: a secret-related variable name, realistic length, character diversity, strong entropy, and non-placeholder context.

Documentation examples, test fixtures, obvious placeholders, masked values, environment references, and lower-confidence strings should produce warnings rather than automatically being called leaked credentials.

Suspected secrets are redacted. The Book must not store or return the raw secret merely to prove that it found one, and Amosclaud must not send a suspected key to an external network service to test whether the credential is valid.

When high-confidence evidence indicates a real exposure, Slapface blocks normal work until the credential is removed from tracked content, rotation/revocation is addressed where appropriate, related history/artifacts are checked, and the repair is verified and recorded.

## Guidelines for Developers

When building Amosclaud:

1. Build toward provider independence rather than deeper permanent dependence on one external platform.
2. Treat a project as repository + workspace + agent + infrastructure + memory + permissions + operational history.
3. Keep identity and capability permissions explicit. Intelligence or confidence never grants authority by itself.
4. Preserve one governed Amosclaud Autonomous experience even when many internal services participate.
5. Prefer real executable workflows over status-only UI.
6. Distinguish implemented code from verified production behavior.
7. Keep secrets outside tracked source and Book content.
8. Update the Book when a meaningful Amosclaud capability or engineering rule changes.
9. Leave a precise handoff when work cannot be finished so the next human or agent does not guess.
10. Physical Amosclaud machines expand runner/model/storage independence, but they do not replace the need for a coherent software platform and developer experience.

## How to Use This Book

Start here for the vision and engineering rules. Continue through the numbered chapters for the platform, Autonomous Agent, model layer, SpaceCodeMe, data system, Actions/CI, applications/connectors, security/identity, Desktop, and physical-computer roadmap.

Humans may read the Book like documentation. Agents may consume it through the same repository-native and Amosclaud-native contract. The Book gives shared knowledge and guidance; authentication, permissions, approvals, and execution controls remain separate governed systems.

**Slapface is the front door to the Book: know what came before, know what Amosclaud is trying to become, and do not build the next line on top of a missing one.**
