# Slapface — Read This Before Repository Work

Slapface is the front door of the Amosclaud Book. Before a human or agent scans, edits, builds, fixes, merges, deploys, or otherwise acts on an Amosclaud-managed repository, the Book must be consulted.

The purpose is not to add another approval queue. The Book is the repository owner's second hand: it remembers what was left unfinished, explains the risk in ordinary sentences, points to the exact Book chapter or handoff, and allows work when the evidence is safe enough to continue.

## The Gatekeeper Rule

For an Amosclaud-managed repository:

1. The request reaches the Book first.
2. Slapface checks for an unfinished blocking handoff.
3. Slapface checks proposed text for high-confidence credential exposure when text is being written or submitted.
4. The Book returns **allowed**, **allowed with warning**, or **blocked**.
5. Only an allowed request proceeds to repository work.
6. A blocked request must repair the listed missing pieces and record safe evidence before work is released.

Owner work does not require a second repetitive approval prompt when the Book allows it. Authentication, repository ownership, permissions, destructive-operation recovery rules, and credential safety still apply. The Book replaces repetitive work approval; it does not replace identity or security.

## Catch the Last Line First

If an agent stopped with unfinished work, Slapface carries that handoff forward. The next agent must receive:

- a safe sentence explaining what is unfinished;
- the Book chapter or anchor that explains the risk;
- the missing pieces that must be repaired;
- a handoff identifier;
- safe verification evidence required to release the block.

An owner or third-party repository owner cannot simply tell the agent to ignore an active Slapface blocker. The missing prerequisite must be repaired first. This prevents a new task from silently building on top of a known broken foundation.

## Secret Safety

The Amosclaud Book must never become a secret store.

It must never record or display a raw API key, token, password, bearer credential, private key, recovery code, or other credential value. If credential-like material is detected, Book storage keeps only safe metadata such as the classification, confidence, type, line number, and a short one-way fingerprint that cannot reconstruct the credential.

Slapface deliberately does not treat every long random string as a leaked token. It uses confidence levels:

- **confirmed secret** — multiple strong signals or a highly specific credential structure; blocks work;
- **probable secret** — enough independent signals make accidental credential exposure likely; blocks work;
- **suspicious** — one or more weak signals deserve review, but work is not blocked automatically.

Placeholder values, environment-variable references, secret-manager references, obvious examples, dummy/test values, hashes, and UUID-like identifiers should not be promoted to a leak merely because they look random.

The detector never validates a suspected credential by sending it to its provider. Secret detection stays local to the Amosclaud repository boundary.

## Example

A developer proposes code containing a literal value assigned to `OPENAI_API_KEY`. If the value has the size and randomness expected of a real credential and is not an obvious placeholder or environment reference, Slapface can classify it as probable or confirmed credential exposure and stop the write before it is committed.

The Book then says, in effect:

**Slapface blocked this repository action because high-confidence credential-like material was found. Remove the literal, use an environment or secret-management reference, rotate the credential if it may already have escaped the editor, record clean evidence, and retry.**

The raw credential is not repeated in that message and is not written into the Book.

## Human and Agent Contract

The same rule applies to Amosclaud's owner, another repository owner, a developer, Amosclaud Autonomous, ChatGPT, Codex, or another connected agent. The Book is repository-scoped: one third-party owner's Book governs only that owner's Amosclaud repository and does not expose or mix another repository's data.

Slapface is a watchdog, not an author. Humans and agents perform the engineering work; the Book collects safe evidence, protects continuity, and decides whether the repository is ready for the next action.
