# Continuous integration

Amosclaud changes are verified from the current pull-request head commit.

## Required verification

Before a pull request is merged:

1. Backend tests must pass.
2. Web assets and CLI integration checks must pass.
3. Docker and platform build checks must pass.
4. CodeQL analysis must complete successfully.
5. Required production deployment checks must report the actual deployment result.

A failed workflow must be investigated from its newest job attempt. Re-running an older workflow does not replace verification of a newer branch commit; push a new corrective commit when the pull-request head has changed.

Repository policy requirements such as approvals, signed commits, and successful deployment environments are separate from source-code test results and must be configured to match the project’s real development workflow.
