# CI Safety Policy

## Validation-only CI

Continuous integration for this repository must be **validation-only**:

- Every branch push and pull request runs dependency installation, application
  compilation (`python -m compileall amoscloud_ai`), and the pytest suite.
- CI must never call deployment commands. The root `main.py` script is not the
  FastAPI application entry point and does not support `--test-guardrails` or
  `--deploy` flags.

## Deployment boundary

- Production deployment is handled exclusively by the dedicated deployment
  workflow, gated to the `main` branch with environment-specific controls.
- Feature branches must never trigger deployments.

## Change management

- Major structural changes are pushed to a new branch for automated CI
  validation before merging to `main`.
- Every autonomous change is recorded in commit history with a clear
  explanation of why the change was made.
