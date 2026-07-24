# Contributing to Amosclaud

Amosclaud is a developer-first, self-hosted platform. Contributions are welcome from developers, testers, technical writers, designers, and infrastructure engineers.

## Development principles

- Repository work is manual-first and auditable.
- Amosclaud Autonomous is the primary execution runtime.
- External model providers are optional integrations, never requirements for core operation.
- Features must return real results and explicit errors; never report unverified work as successful.
- Security, user ownership, and self-hosting take priority over convenience.

## Local setup

Requirements:

- Python 3.11 or newer
- Git
- Docker and Docker Compose for full-stack testing

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

Run the standard validation suite:

```bash
python scripts/workspace_task.py test
python scripts/workspace_task.py quality
python scripts/workspace_task.py build
```

## Contribution workflow

1. Create an issue for substantial changes.
2. Create a focused branch from `main`.
3. Make the smallest complete change that solves the problem.
4. Add or update tests.
5. Run the complete local validation suite.
6. Open a pull request with evidence of the result.
7. Merge manually only after required checks pass.

Recommended branch names:

- `feature/<short-name>`
- `fix/<short-name>`
- `docs/<short-name>`
- `security/<short-name>`

## Pull request requirements

Every pull request should include the problem, implementation approach, affected systems, tests performed, screenshots for interface changes, deployment or migration notes, and known limitations.

Do not mix unrelated refactors into a feature or bug-fix pull request.

## Code quality

- Keep functions focused and readable.
- Prefer explicit types and structured response models.
- Validate all user-controlled paths, branches, URLs, and identifiers.
- Never commit secrets, tokens, credentials, or private keys.
- Preserve backward compatibility unless a breaking change is clearly documented.
- Return truthful states: queued, running, success, failed, or cancelled.

## Autonomous runtime rules

Build, test, review, deploy, and monitor actions should route through Amosclaud Autonomous with `use_agent: false` by default. Optional model reasoning may be added behind an explicit user choice, but it must never be required for repository or deployment workflows.

## Bug reports

Use the bug report template and include the Amosclaud version or commit SHA, operating system, deployment platform, exact reproduction steps, expected and actual behavior, and sanitized logs.

## Security issues

Do not open a public issue for a vulnerability. Follow `SECURITY.md`.

## License

By contributing, you agree that your contribution may be distributed under the repository's applicable license terms.