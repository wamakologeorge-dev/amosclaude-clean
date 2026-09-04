# Amosclaud Crash Shield

Amosclaud Crash Shield is a lightweight pre-deployment crash-risk scanner for Amosclaud source code. It is designed to surface dangerous lines before they reach users.

## What it detects

The first release checks Python and JavaScript/Node sources for:

- syntax errors that would prevent a process from starting;
- explicit process termination (`sys.exit`, `SystemExit`, `process.exit`, and related calls);
- module-level required environment lookups that can fail during service import/startup;
- HTTP calls without timeouts that can exhaust workers when an upstream stalls;
- subprocess calls without timeouts;
- obvious unbounded loops;
- Node syntax failures via `node --check`.

## GitHub annotations

The `Amosclaud Crash Shield` workflow runs on pull requests and pushes to `main`. Findings are emitted as annotations pointing at the risky file and line, with a severity and rule ID.

The initial rollout is advisory so existing findings do not unexpectedly block development. After the existing baseline is reviewed, CI can pass `--fail-on-critical` to block critical crash risks.

## Local usage

```bash
python scripts/ci/amosclaud_crash_shield.py --root .
```

Generate GitHub-style annotations and a machine-readable report:

```bash
python scripts/ci/amosclaud_crash_shield.py \
  --root . \
  --github-annotations \
  --json-report amosclaud-crash-shield-report.json
```

Block on critical findings:

```bash
python scripts/ci/amosclaud_crash_shield.py --root . --fail-on-critical
```

## Production safety

Static scanning reduces preventable crashes but cannot guarantee that a production service never fails. Amosclaud should pair Crash Shield with health/readiness probes, staged or canary releases, automatic rollback, runtime exception telemetry, resource monitoring, and redundant service instances so a single bad process does not take the platform offline.
