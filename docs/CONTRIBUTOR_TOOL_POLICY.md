# Amosclaud Contributor Tool Sovereignty Policy

**Policy ID:** `AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1`
**Status:** Permanent repository governance
**Applies to:** every human contributor, maintainer, bot, autonomous agent, workflow, generated patch, and integration.

## Mandatory Amosclaud-first order

Every contributor must follow this order before adding, calling, installing, or integrating a tool, action, SDK, library, service, model adapter, workflow component, or automation:

1. **Scan the Amosclaud repository first.** Identify whether Amosclaud already contains a tool, package, script, service, workflow, action, adapter, or contract that provides the required capability.
2. **Reuse or extend Amosclaud’s existing capability.** When a suitable Amosclaud-owned implementation exists, contributors must use it or improve it instead of introducing a competing external implementation.
3. **Use an external tool only when Amosclaud has no suitable equivalent.** The pull request must document the repository scan, the missing capability, why the existing Amosclaud components are insufficient, and why the external dependency is necessary.
4. **Constrain every approved exception.** External tools must be pinned, least-privilege, narrowly scoped, verified, documented, and removable without breaking Amosclaud’s core operation.
5. **Preserve Amosclaud ownership.** External services may support Amosclaud, but they must not silently replace Amosclaud’s native execution, verification, policy, identity, storage, or evidence contracts.

## Required pull-request evidence

A contribution that adds or expands an external dependency must include:

- the Amosclaud repository paths and search terms inspected;
- the existing Amosclaud components considered;
- the exact capability gap that remains;
- the external dependency name and pinned version or commit;
- permissions, secrets, network access, and data boundaries;
- focused verification proving the integration works;
- a failure, fallback, and removal plan;
- owner approval when the dependency affects protected operations, credentials, deployment, repository writes, or user data.

“No equivalent found” without recorded repository evidence is not sufficient.

## Non-removal and non-bypass rule

This policy must not be removed, weakened, bypassed, renamed to avoid enforcement, or converted into optional guidance by any contributor, bot, agent, maintainer, workflow, or automation.

Any governance change touching this policy must:

- preserve or strengthen the Amosclaud-first requirement;
- pass the `Amosclaud Workflow Policy / policy` check;
- receive repository-owner code-owner approval;
- keep the policy marker and automated guard intact;
- state the reason, evidence, security impact, and rollback plan.

A change that removes the policy marker, protected files, guard invocation, required pull-request evidence, or code-owner coverage is invalid and must fail verification.

## Formal review safety contract

Amosclaud Bot pull-request review must remain read-only and non-blocking:

- it checks out trusted default-branch code, not pull-request code;
- it submits only GitHub `COMMENT` reviews;
- it binds the review to the exact pull-request head SHA;
- it refuses a stale review when the head changes;
- it does not approve, request changes through GitHub authority, merge, push, or receive protected App secrets.

A recommendation inside the review body is evidence only. Repository protections and human approval retain merge authority.

## Advanced Security repair contract

Security findings remain blocking until their root cause is fixed and all security checks rerun successfully.

The trusted security-repair bridge may accept only the protected workflow allowlist documented in `docs/AMOSCLAUD_SECURITY_REPAIR_LOOP.md`. It must:

- authenticate the Amosclaud GitHub App and verify repository installation access;
- verify the open pull request and exact failed head SHA;
- reject stale results after the branch moves;
- dispatch the existing Amosclaud Repair Control Plane rather than create a competing fixer;
- fail closed when authentication, evidence, or dispatch cannot be verified;
- never suppress, dismiss, downgrade, or disable a security finding to make a check pass;
- never merge or force-push.

Any open CodeQL alert and every newly introduced vulnerable dependency covered by the repository gates is treated as blocking regardless of low, moderate, high, or critical severity. Ordinary lint and test failures remain blocking engineering failures but must not be falsely labeled as security vulnerabilities.

## Enforcement files

The protected contract includes the core governance files:

- `docs/CONTRIBUTOR_TOOL_POLICY.md`
- `AGENTS.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/CODEOWNERS`
- `.github/workflows/policy.yml`
- `scripts/ci/contributor_tool_policy_guard.py`
- `tests/test_contributor_tool_policy_guard.py`

It also protects the formal-review implementation:

- `.github/workflows/amosclaud-bot-review.yml`
- `amosclaud_bot/review_publisher.py`
- `tests/test_amosclaud_review_publisher.py`
- `docs/AMOSCLAUD_BOT_FORMAL_REVIEW.md`

And the Advanced Security repair connection:

- `.github/workflows/codeql.yml`
- `.github/workflows/fortify.yml`
- `.github/workflows/amosclaud-dependency-threat-gate.yml`
- `.github/workflows/amosclaud-security-repair-bridge.yml`
- `scripts/ci/advanced_security_gate.py`
- `amoscloud_ai/github_app_connection.py`
- `amoscloud_ai/security_repair_bridge.py`
- `tests/test_advanced_security_gate.py`
- `tests/test_github_app_connection.py`
- `tests/test_security_repair_bridge.py`
- `docs/AMOSCLAUD_SECURITY_REPAIR_LOOP.md`

The `Amosclaud Workflow Policy / policy` check runs on every pull request without path filters. The repository-owned guard parses the effective workflow structure and active shell commands, parses effective CODEOWNERS rules while ignoring comments, validates the review event, verifies trusted checkouts, protects the security workflow allowlist, and locks the repair dispatch target to the existing Amosclaud Repair Control Plane.

Regression tests reject path-filtered enforcement, commented-out guard commands, renamed enforcement steps, commented ownership rules, removed ownership rules, removed policy markers, automatic review approval, pull-request-code checkout, protected secrets in the review workflow, broadened security sources, replaced repair targets, and weakened low-severity dependency blocking.

## Required GitHub branch rules

The protected `main` branch must require:

- status check `Amosclaud Workflow Policy / policy`;
- pull requests before merging;
- approval from code owners;
- dismissal of stale approvals when protected files change;
- conversation resolution before merging;
- no force pushes and no branch deletion;
- no bypass for contributors, bots, apps, or administrators where the GitHub plan and ownership settings permit it.

Repository files enforce the policy during review and validation. GitHub branch rules enforce it at merge time. Without those owner-controlled branch rules, an administrator can technically bypass repository files, so these settings are a mandatory part of the policy rather than optional guidance.
