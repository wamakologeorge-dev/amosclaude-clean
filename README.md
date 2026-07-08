# 🚀 Amoscloud AI

Amoscloud AI is a Python-based automation scaffold for CI/CD, deployment, repository operations, and database management. The repository currently includes modular services and orchestration code under `src/` plus Docker-based infrastructure for local development and testing.

## What this repository contains

This project is organized around a small set of building blocks:

- `src/core/ci_orchestrator.py` - orchestration logic for continuous integration flows
- `src/core/smart_deployer.py` - deployment workflow helpers
- `src/core/code_analyzer.py` - code analysis utilities
- `src/core/git_manager.py` - Git-oriented helpers
- `src/amoscloud_ai/services/` - deployment and database services
- `src/database/` - database access helpers
- `tests/` - placeholder test package for future automation coverage

## Prerequisites

Before you begin, make sure you have:

- Python 3.9 or newer
- Docker and Docker Compose
- Git

## Quick start with Docker Compose

The easiest way to bring up the local environment is with Docker Compose.

1. Clone the repository:
   ```bash
   git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
   cd amosclaude-clean
   ```
2. Build and start the stack:
   ```bash
   docker compose up --build
   ```
3. The compose file starts:
   - PostgreSQL on port `5432`
   - Redis on port `6379`
   - The application API container on port `8000`
   - A worker container for background tasks
   - Nginx on ports `80` and `443`

4. To stop the stack:
   ```bash
   docker compose down
   ```

5. To remove persisted data volumes:
   ```bash
   docker compose down -v
   ```

## Local Python development

If you want to work directly with the Python modules, use a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The repository currently provides a Python package scaffold, so you can import modules from `src/` and extend them with your own entrypoints.

## Running tests

The repository is set up to use `pytest` for automated tests.

```bash
python -m pytest -q
```

## Configuration

The Docker stack uses the following environment variables:

- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `ENVIRONMENT` - runtime environment name
- `LOG_LEVEL` - logging verbosity

These values are defined in `docker-compose.yml` for the local development stack.

## Project layout

```text
.
├── Dockerfile
├── docker-compose.yml
├── setup.py
├── src/
│   ├── ai/                # AI-related helpers
│   ├── amoscloud_ai/      # service modules
│   ├── core/              # orchestration and deployment helpers
│   └── database/          # database helpers
├── tests/
└── README.md
```

## Typical development workflow

1. Make changes in the relevant module under `src/`.
2. Add or update tests in `tests/`.
3. Run the test suite locally.
4. Rebuild or restart the Docker stack as needed.

## Troubleshooting

- If Docker cannot start a service, check whether ports `80`, `443`, `5432`, and `6379` are already in use.
- If the Python environment cannot import modules, verify that you are running from the repository root and that your virtual environment is active.
- If you modify the compose configuration, rerun `docker compose up --build` to rebuild containers.

## Next steps

This repository is a starting point for a larger automation platform. The most natural next steps are:

- implement a real CLI or web entrypoint
- add concrete service adapters for CI providers and deployment targets
- expand the test suite around the orchestration and deployment services

