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

## Enforcement files

The following files form one protected policy contract:

- `docs/CONTRIBUTOR_TOOL_POLICY.md`
- `AGENTS.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/CODEOWNERS`
- `.github/workflows/policy.yml`
- `scripts/ci/contributor_tool_policy_guard.py`
- `tests/test_contributor_tool_policy_guard.py`

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
