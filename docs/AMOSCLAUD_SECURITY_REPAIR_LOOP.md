# Amosclaud Advanced Security repair loop

The security repair loop connects failed GitHub security workflows to Amosclaud's existing bounded Repair Control Plane.

## Approved security sources

The trusted bridge accepts only these workflow names:

- `CodeQL`
- `Amosclaud Dependency Threat Gate`
- `Fortify AST Scan`

A workflow must finish with `failure`, `timed_out`, `action_required`, or `startup_failure` before the bridge considers it repairable.

## Connection sequence

```text
Security workflow fails
→ trusted default-branch bridge starts
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
```

The bridge does not create a second fixer. It delegates to `.github/workflows/amosclaud-repair-control-plane.yml`, which already owns failure reproduction, candidate generation, verification, sensitive-change approval, stale-branch protection, and repair publication.

## Safety rules

The bridge must never:

- execute pull-request code;
- dispatch a repair for an unapproved workflow name;
- dispatch a repair for a successful or skipped security workflow;
- repair a closed pull request;
- repair a stale commit after the PR head moved;
- dismiss or suppress a security alert;
- reduce security severity or disable a query to make a check pass;
- print the App JWT or installation token;
- merge a pull request;
- force-push.

A failed dispatch is reported as `BLOCKED`; it is never described as a requested or completed repair.

## Required GitHub App permissions

The installed Amosclaud GitHub App requires only the permissions needed for its approved operations. For this bridge, the installation must be able to:

- read repository and pull-request metadata;
- dispatch GitHub Actions workflows.

The separate verified-repair publication path may also require repository content write permission. Branch protection and required security checks remain authoritative after any repair commit.

## Owner-controlled activation

After the trusted implementation is merged, configure these protected values:

```text
GITHUB_APP_SLUG
GITHUB_APP_ID
GITHUB_APP_INSTALLATION_ID
GITHUB_APP_BOT_USER_ID
GITHUB_APP_PRIVATE_KEY
```

The bridge fails closed when App authentication, installation access, exact-head validation, or Repair Control Plane dispatch cannot be verified.
