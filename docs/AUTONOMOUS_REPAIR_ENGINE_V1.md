# Amosclaud Autonomous Repair Engine v1

## Mission

Given a repository, Amosclaud diagnoses static blockers, applies only deterministic low-risk repairs, verifies the result with real commands, stores repair evidence, and reports PASS only when all available evidence passes.

## Included package

- **Doctor**: required-file checks, merge-conflict detection, UTF-8 checks, Python/JSON/shell syntax, workflow YAML checks, immutable action pinning, and missing local web assets.
- **Fixer**: trailing whitespace, final newlines, YAML tab indentation, and approved action pin replacements.
- **Verifier**: runs explicit command arrays with timeouts and captures return codes, duration, and bounded output.
- **Reporter**: JSON and Markdown evidence reports.
- **Repair Memory**: append-only JSONL records at `.amosclaud/repair-memory.jsonl`.
- **GitHub workflow**: pull-request diagnosis and manually approved deterministic repair execution.

## Safety boundaries

The v1 fixer does not automatically rewrite critical syntax errors, merge conflicts, missing business logic, secrets, deployments, database migrations, or infrastructure. Those are reported as critical and require a targeted repair plan or human approval.

No PASS is emitted when:

- Doctor still has a critical or repairable finding;
- a configured verification command fails or times out;
- evidence is unavailable.

## CLI

```bash
amosclaud-repair . \
  --required pyproject.toml \
  --verify "python -m pytest -q" \
  --json repair-report.json \
  --markdown repair-report.md
```

Apply deterministic safe repairs:

```bash
amosclaud-repair . --apply --verify "python -m pytest -q"
```

## Lifecycle

```text
ANALYZING
  -> HEALTHY / REPAIRABLE / CRITICAL
  -> REPAIRING (only deterministic safe findings)
  -> VERIFYING
  -> PASS / FAIL
  -> REPORT + MEMORY
```

## Extending v1

New repair strategies should be registered as narrowly scoped deterministic transformations with tests. Generative repairs must use a separate approval policy, isolated branch, diff limits, and independent verification before they can be merged.
