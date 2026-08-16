# Dependency Review Action Exception Evidence

**Policy:** `AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1`

## Repository scan

Before retaining `actions/dependency-review-action`, the repository-owned dependency and security capabilities were reviewed, including:

- `scripts/ci/advanced_security_gate.py`
- `scripts/ci/bandit_pr_gate.py`
- `.github/workflows/codeql.yml`
- `.github/workflows/fortify.yml`
- `.github/workflows/amosclaud-dependency-threat-gate.yml`
- the native Amosclaud Repair Control Plane

Search terms included dependency, advisory, manifest diff, lockfile, vulnerability, CVE, and dependency review.

## Capability gap

The repository-owned scanners evaluate source and known security findings, but they do not reproduce GitHub's pull-request dependency graph comparison across supported package manifests and lockfiles. That graph-aware base-versus-head advisory evaluation is the specific remaining gap.

## Approved external dependency

- Action: `actions/dependency-review-action`
- Pinned commit: `a1d282b36b6f3519aa1f3fc636f609c47dddb294`
- Recorded release: `v5.0.0`
- Workflow permissions: `contents: read`
- Trigger: pull requests targeting `main`
- Enforcement: every advisory at low severity or greater is blocking; development, runtime, and unknown scopes are included; warn-only mode is disabled.

The action receives the GitHub event and read-only repository metadata required to compare dependency changes. It receives no Amosclaud, Ollama, GitHub App, deployment, or model credentials.

## Verification

The workflow pin is immutable, permissions are read-only, and the action's result is enforced as a required threat gate. The repository policy workflow verifies that the threat settings remain fail-closed.

## Fallback

If the action is unavailable or its trust boundary changes, disable the external step and block dependency-changing pull requests until a repository-owned manifest-diff and advisory evaluator can provide equivalent evidence. CodeQL, Bandit/Fortify, and the Amosclaud security repair loop remain active but are not treated as equivalent dependency-diff evidence.

## Removal plan

Replace this exception when Amosclaud has a repository-owned component that can:

1. identify dependency manifest and lockfile changes;
2. resolve the exact base and head dependency graphs;
3. evaluate advisories at every configured scope and severity;
4. publish an exact-commit blocking status; and
5. emit evidence compatible with the native Ollama-backed Repair Control Plane.

Any version, permission, data-flow, or action-owner change requires a new review of this exception before adoption.
