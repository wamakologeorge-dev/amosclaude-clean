# Amosclaud Isolated Runner Image

Build this image on the dedicated worker or server-station host:

```bash
docker build -t amosclaud/runner-python-node:1 runner
```

Set `AMOSCLAUD_RUNNER_IMAGE=amosclaud/runner-python-node:1` on the Celery worker.
The API service does not need Docker access and must not receive the Docker socket.

The worker launches each job with no network, a read-only root filesystem, all
capabilities dropped, `no-new-privileges`, a non-root user, a bounded temporary
filesystem, CPU/memory/PID limits, and a strict timeout. Only the owner-scoped
workspace is mounted into `/workspace`.

Project dependencies must be installed into the workspace, for example:

```text
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
```

Because shell executables are blocked, each configured command must name one
allowlisted executable directly. Do not use `sh -c`, pipes, redirects, command
substitution, or chained shell commands.
