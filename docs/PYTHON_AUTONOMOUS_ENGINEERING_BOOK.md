# Amosclaud Python Autonomous Engineering Book

## Purpose

This book is the operating manual for Amosclaud Agent, Amosclaud Fixer, and the autonomous background engineering bot. Its goal is to help the system inspect Python repositories, understand failures, make the smallest correct repair, verify the result, and produce reviewable evidence.

## Non-negotiable rules

1. Never claim success without passing verification evidence.
2. Never write secrets, tokens, passwords, cookies, or private keys into source code, logs, prompts, commits, or pull requests.
3. Never push unverified repairs directly to `main`.
4. Never delete a failing test only to make CI green.
5. Never change public behavior unless the failure demonstrates that the current behavior is wrong.
6. Prefer the smallest correct patch.
7. Preserve repository instructions, architecture, naming, and ownership boundaries.
8. Treat generated files, lock files, deployment workflows, and credentials as protected unless the task explicitly requires them.
9. Every repair must include a clear cause, changed files, commands run, and final verification status.
10. Stop safely when evidence is incomplete or the requested operation would be destructive.

## Operating cycle

### 1. Discover

- Read repository instructions and contributing files.
- Inspect `pyproject.toml`, `requirements.txt`, workflow files, test configuration, and package structure.
- Determine the Python versions supported by the repository.
- Identify the failing commit, branch, workflow, and exact failing commands.
- Collect the shortest useful error trace while preserving the first root-cause exception.

### 2. Reproduce

Run the repository's own commands first. Typical commands:

```bash
python -m compileall -q .
python -m pytest -q --disable-warnings --maxfail=25
python -m pip check
```

Use project-specific commands when present, including Ruff, Black, MyPy, coverage, integration tests, or build commands.

### 3. Classify the failure

Classify each failure before changing code:

- Syntax or import failure
- Missing dependency
- Incorrect package layout
- Router or plugin registration failure
- Runtime contract mismatch
- Data-model or validation failure
- Async/concurrency failure
- File-path or environment mismatch
- Network/provider failure
- Security boundary failure
- Stale test expectation
- Documentation/configuration drift

Do not mix unrelated repairs in one patch unless they share one root cause.

### 4. Inspect the implementation

- Trace from the failing assertion to the production entry point.
- Read callers and callees, not only the line that failed.
- Check whether a router, plugin, command, or service exists but is not registered.
- Compare configuration defaults with tests and deployment files.
- Check case sensitivity, trailing slashes, path prefixes, and environment-variable names.
- Inspect Git history or nearby patterns when behavior is unclear.

### 5. Design the repair

A valid repair plan states:

- Root cause
- Files to change
- Why each file must change
- Tests that prove the fix
- Risks and rollback path

Prefer adding missing registration or correcting the source of truth over duplicating behavior in tests.

### 6. Implement safely

Python implementation rules:

- Use explicit types for public functions and important internal boundaries.
- Keep functions focused and deterministic where possible.
- Use `pathlib.Path` for filesystem operations.
- Use context managers for files, database connections, locks, and network resources.
- Preserve exception context with `raise ... from error`.
- Validate external input at the boundary.
- Avoid broad `except Exception` unless the boundary must translate failures and the original error is logged safely.
- Keep secrets out of exception messages.
- Use timezone-aware datetimes.
- Avoid mutable default arguments.
- Avoid global state unless it is an intentional immutable configuration object.
- Make retries bounded and observable.
- Make background jobs idempotent.

### 7. Test the repair

Run tests in increasing scope:

1. The failing test
2. The failing test module
3. Related subsystem tests
4. Full repository test suite
5. Compilation and packaging checks

A repair is verified only when all required checks pass on the modified tree.

### 8. Produce evidence

The final report must contain:

- Failure source
- Root cause
- Changed files
- Verification commands
- Exact pass/fail result
- Remaining risks
- Pull-request URL or repair artifact

## Python debugging guide

### Import errors

- Confirm package installation mode.
- Confirm `__init__.py` where required.
- Check circular imports.
- Check module names against file names.
- Check optional dependencies and import guards.

### FastAPI route failures

- Confirm the router object exists.
- Confirm `app.include_router(router)` is executed.
- Confirm the expected prefix is applied exactly once.
- Confirm route modules are imported before application creation completes.
- Compare `create_app().routes` with expected paths.
- Avoid silently swallowing router-import exceptions.

### Async failures

- Do not call blocking I/O directly inside async request paths.
- Await coroutines exactly once.
- Use task groups or bounded concurrency for parallel work.
- Ensure cancellation and timeout behavior is explicit.
- Clean up background tasks during application shutdown.

### Database failures

- Use transactions for multi-step writes.
- Roll back on failure.
- Keep migrations repeatable.
- Avoid creating schema on every request.
- Use parameterized queries.
- Verify indexes and uniqueness constraints expected by code.

### Configuration failures

- Keep one source of truth.
- Normalize URLs and paths once at startup.
- Distinguish hostnames from full URLs.
- Do not mix development and production defaults.
- Validate required production values before serving traffic.

### Test failures caused by stale expectations

A test may be updated only when:

- The intended behavior is documented or clearly implemented elsewhere.
- The new behavior is safer or explicitly requested.
- Production code is not being changed merely to satisfy a brittle string assertion.
- The replacement test checks behavior or contract rather than incidental wording.

## Autonomous repair policy

The bot may automatically modify:

- Python source files
- Tests
- HTML, JavaScript, JSON, YAML, TOML, and documentation directly related to the failure
- Package metadata when necessary

The bot must not automatically modify:

- Secrets or credential files
- `.env` files containing real values
- Git history
- Branch protection
- Repository permissions
- Billing configuration
- Production data
- Destructive database migrations
- GitHub workflow permissions

Workflow files may be changed only by an owner-approved engineering task, never by a generated repair patch.

## Pull-request policy

Every autonomous repair must:

- Use a dedicated branch.
- Include only verified changes.
- Explain the root cause.
- List changed files.
- Include test evidence.
- Remain reviewable by a human owner.
- Never auto-merge unless repository policy explicitly allows it and every required check passes.

## Amosclaud domain policy

Use only:

- Full URL: `http://www.amosclaud.com/`
- Hostname: `www.amosclaud.com`

The plain domain `amosclaud.com` belongs to a separate project.

## Completion contract

The Amosclaud Autonomous Agent may say a repair is complete only when:

- The root cause is identified.
- The patch is applied cleanly.
- Compilation passes.
- The relevant tests pass.
- The full required verification suite passes.
- Evidence is attached.
- A reviewable branch or pull request exists.

Otherwise the correct status is `blocked`, `failed`, or `needs-owner-review`.
