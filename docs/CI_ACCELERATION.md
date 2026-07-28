# Amosclaud CI Acceleration

This performance layer reduces pull-request feedback time without weakening the
repository's complete test, security, package, and live-server checks.

## Fast pull-request gate

`Fast PR Gate` runs only when Python, YAML, workflow, dependency, or project
configuration files change. It installs a minimal tool set and validates only the
changed files:

- Python syntax and unresolved merge markers;
- YAML syntax and unresolved merge markers;
- Black formatting;
- isort import ordering;
- focused tests for the gate and repository-behavior automation.

The fast gate is an early feedback lane. It is not a replacement for the full
Python, Docker, CodeQL, Fortify, package, and live-server workflows.

## Python dependency caching

The primary Python workflows use `setup-python` pip caching with an explicit
dependency file. They no longer upgrade pip or install test tools separately when
those tools already exist in `requirements.txt`.

Cache entries are reusable from the current branch, the default branch, and the
base branch allowed by GitHub's cache isolation rules.

## Docker layer caching

Docker image and platform-verification jobs use Buildx with a GitHub Actions cache.
Each image has a separate cache scope so parallel matrix builds do not overwrite
one another. The control-plane image shares one scope between image verification
and the platform smoke test.

The first cold build can still take several minutes. Later builds can reuse unchanged
base, dependency, and application layers.

## Optional accelerated runners

All accelerated workflows use this runner expression:

```yaml
runs-on: ${{ vars.AMOSCLAUD_CI_RUNNER || 'ubuntu-latest' }}
```

The default remains `ubuntu-latest`. To use Blacksmith, WarpBuild, or another
trusted runner provider:

1. Install and authorize the provider for this repository.
2. Copy the exact runner label supplied by that provider.
3. Create the repository variable `AMOSCLAUD_CI_RUNNER` with that label.
4. Run a draft pull request and verify that every required job starts and finishes.

A runner label is non-sensitive configuration and belongs in a repository variable,
not a secret. Never place provider credentials, cloud keys, or tokens in this variable.

## Timing expectations

The fast gate is designed for sub-minute warm feedback on small changes. Cold package
installs, cold Docker builds, queue delays, network latency, and the complete test
suite cannot be guaranteed to finish in under one minute.

## Autonomous repair agents

This change does not add a new external Copilot or Claude action with repository write
permissions. Amosclaud already has approval-gated repair and bot workflows. Any future
external coding agent must use a separate pull-request branch, read-only permissions by
default, immutable action versions, and explicit human approval before writes or merges.
