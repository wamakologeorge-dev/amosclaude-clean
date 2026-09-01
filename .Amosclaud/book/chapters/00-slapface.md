# Slapface

Slapface is the Amosclaud Book introduction and pre-work continuity gate. It runs before repository inspection, build, fix, deployment preparation, or other engineering execution.

## Why Slapface Exists

An agent can stop with unfinished work, leave a missing dependency, or discover a risk that the next agent does not know about. Starting a new build on top of that unfinished state can create avoidable failures. Slapface makes the unfinished handoff impossible to silently skip inside Amosclaud's governed agent paths.

## The Slap

When a previous agent records an unfinished handoff, Slapface presents the next agent with:

- the last unfinished Book chapter;
- a direct link back to that chapter;
- the exact next line or task that was left unfinished;
- the error or risk that may happen if work continues too early;
- the missing pieces that must be repaired;
- the handoff ID that identifies the blocker.

The Slapface page attempts to copy the chapter link automatically. Browsers may require clipboard permission, so the page also provides a manual Copy link button.

## Hard Gate Rule

If Slapface is blocked, normal repository work is not allowed. This remains true even when an account owner asks the agent to ignore the warning. Owner approval does not become a bypass token.

The only permitted work while blocked is scoped remediation for the active handoff. Remediation must reference the matching handoff ID. Slapface is released only after the repair is represented by a Book change report whose verification state is recorded as verified, passed, completed, success, or succeeded.

## Provider Independence

The rule belongs to Amosclaud, not GitHub. A repository can come from Amosclaud, GitHub, local storage, or another connected provider; Amosclaud-native agents still receive the same Slapface preflight before repository execution.

## Agent Rule

Before you inspect or change repository contents:

1. Request Slapface preflight for the current account/work scope.
2. If clear, continue under the normal Amosclaud authorization rules.
3. If blocked, tell the account owner what Slapface found and show the chapter link, next line, risk, and missing pieces.
4. Do not continue the original build merely because the owner says to ignore Slapface.
5. Repair the missing pieces under Slapface remediation mode, verify the repair, record the Book change report, resolve the handoff, and only then resume the original task.

Slapface is continuity protection, not a substitute for authentication, authorization, testing, security review, or deployment controls.
