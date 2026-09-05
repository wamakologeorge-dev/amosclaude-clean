# Amosclaud Crash Shield rollout

1. **Advisory** — annotate crash-risk lines without blocking existing work.
2. **Baseline** — review and fix or explicitly accept existing findings.
3. **Gate new critical risks** — enable `--fail-on-critical` for pull requests after the baseline is clean.
4. **Pre-deploy verification** — run Crash Shield together with application tests, health checks, and deployment smoke tests.
5. **Runtime protection** — combine static warnings with health probes, automatic rollback, telemetry, restart policies, and redundant instances.

The goal is defense in depth: catch preventable crash risks before merge, detect deployment failures before traffic is shifted, and recover automatically when an unexpected runtime failure still occurs.
