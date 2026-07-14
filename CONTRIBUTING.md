# Contributing to Amosclaud AI

Thank you for contributing.

## Development setup

1. Fork or clone the repository.
2. Create a branch from `main`.
3. Copy `.env.example` to `.env` and add only local values.
4. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Run the application:

   ```bash
   python -m amoscloud_ai.main
   ```

## Before submitting a pull request

Run the checks used by CI:

```bash
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
pytest
```

Keep changes focused, avoid committing generated files or secrets, and update documentation when behavior changes.

## Pull requests

Describe what changed, why it changed, how it was tested, and any deployment or compatibility impact. Link related issues where applicable.

## Security

Do not report vulnerabilities in public issues. Follow `SECURITY.md` instead.
