# Amosclaud Advanced Security repair loop

The security repair loop connects GitHub security failures to Amosclaud's existing bounded Repair Control Plane. It does not create a second fixer.

## Approved security sources

The general trusted bridge accepts only these original pull-request workflow names:

- `CodeQL`
- `Amosclaud Dependency Threat Gate`
- `Fortify AST Scan`

A source must finish with `failure`, `timed_out`, `action_required`, or `startup_failure` before the bridge considers it repairable.

CodeQL has two distinct paths:

1. If CodeQL analysis itself fails, `Amosclaud Security Repair Bridge` receives the original CodeQL run and may route its exact PR revision to the fixer.
2. If analysis succeeds, `Amosclaud CodeQL Threat Gate` runs from trusted default-branch code, reads open alerts for the original PR, and treats every alert as blocking. When it detects a threat or cannot obtain trustworthy alert evidence, it invokes the same bridge while the original CodeQL `workflow_run` event still contains the PR number and head SHA. It then remains failed so the PR stays blocked.

The trusted CodeQL gate is not accepted as a later second-level bridge source because that later workflow run would no longer be authoritative for the original PR head. This prevents duplicate or misdirected repair dispatches.

## Connection sequence

```text
Security analysis or trusted threat gate detects a blocker
→ trusted default-branch code keeps the original PR event
→ Amosclaud GitHub App authenticates
→ short-lived installation token is created
→ installation access to the repository is verified
→ open pull request and exact head SHA are verified
→ existing Amosclaud Repair Control Plane is dispatched
→ failure is reproduced without repair credentials
→ bounded candidate is generated
→ credential-free verification runs
→ only a verified repair may be published
→ all PR and security checks rerun
→ the PR remains blocked until every threat is cleared
```

The bridge delegates to `.github/workflows/amosclaud-repair-control-plane.yml`, which already owns failure reproduction, candidate generation, verification, sensitive-change approval, stale-branch protection, and repair publication.

## Security gates

- CodeQL runs extended queries and the trusted gate blocks every open PR alert.
- Dependency Review blocks every newly introduced vulnerable dependency from low through critical severity and across development, runtime, and unknown scopes.
- The Fortify-compatible AST gate scans the exact base and head revisions with the same pinned scanner. Every finding introduced by the head is blocking at every severity. Existing base findings remain visible repository security debt and are reported by scheduled full audits.

## Safety rules

The bridge and trusted gates must never:

- execute pull-request code while holding App credentials;
- dispatch a repair for an unapproved workflow name;
- dispatch a repair for a successful or skipped original security workflow;
- repair a closed pull request;
- repair a stale commit after the PR head moved;
- dismiss or suppress a security alert;
- reduce security severity, add suppression flags, or disable a query to make a check pass;
- print the App JWT or installation token;
- merge a pull request;
- force-push.

A failed authentication, evidence lookup, or dispatch is reported as `BLOCKED`; it is never described as a requested or completed repair.

## Required GitHub App permissions

The installed Amosclaud GitHub App requires only the permissions needed for its approved operations. For security routing, the installation must be able to:

- read repository and pull-request metadata;
- dispatch GitHub Actions workflows.

The separate verified-repair publication path may also require repository content write permission. Branch protection and required security checks remain authoritative after any repair commit.

## Owner-controlled activation

After the trusted implementation is merged, configure these protected values:

```text
GITHUB_APP_SLUG=amosclaud-bot
GITHUB_APP_ID=<numeric App id>
GITHUB_APP_INSTALLATION_ID=<numeric installation id>
GITHUB_APP_BOT_USER_ID=<numeric bot user id>
GITHUB_APP_PRIVATE_KEY=<protected PEM value>
```

The `workflow_run`-based trusted gates become active only after their workflow definitions exist on the repository's default branch. Their YAML and policy contracts can be validated in this pull request, but the live event path must be proven after merge through a real CodeQL run and signed App installation.
