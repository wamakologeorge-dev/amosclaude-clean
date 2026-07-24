# Amosclaud Railway backend build

The root `Dockerfile` is the production backend image for Amosclaud.

It installs the required runtime packages directly and no longer depends on a separate `COPY requirements.txt` Docker layer. This avoids Railway build failures caused by an incomplete or stale build context while keeping the Amosclaud backend deployment self-contained.

Required Railway source settings:

- Branch: `main`
- Root directory: repository root (`.`)
- Dockerfile: `Dockerfile`

The build verifies that `amoscloud_ai/main.py` is present and fails with an explicit source-context error if Railway is pointed at the wrong folder.
