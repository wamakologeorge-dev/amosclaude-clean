# Security Policy

## Supported Versions

Security fixes are applied to the latest code on the `main` branch. Older branches and archived releases are not guaranteed to receive updates.

## Reporting a Vulnerability

Please do not open a public issue for a suspected vulnerability or exposed credential.

Use GitHub's private vulnerability reporting feature for this repository when available. Include:

- A clear description of the issue
- Steps to reproduce it
- The affected files, endpoints, or versions
- The potential impact
- Any suggested mitigation

You can expect an initial acknowledgement within 7 days. Confirmed vulnerabilities will be prioritized based on severity and impact.

## Secrets

Never commit API keys, tokens, passwords, private keys, or populated `.env` files. Use example environment files only for documented placeholders and store real values in GitHub Secrets or the deployment platform's secret manager.

## Amosclaud Controlled-Power Model

Amosclaud is intentionally designed to retain strong development capability while reducing accidental high-risk changes.

The repository security policy is defined in `.amosclaud/security.yml`.

Under this model:

- Amosclaud may inspect, review, verify, create branches, push feature-branch changes, and open pull requests.
- Amosclaud-Fixer write operations remain limited to trusted repository collaborators.
- `main` should receive changes through pull requests rather than routine direct development writes.
- High-risk files such as GitHub Actions workflows, deployment configuration, authentication/permission code, `SECURITY.md`, and `CODEOWNERS` require human review before merge.
- Read-only inspection and review operations must not modify the repository.
- Repair work must be verified before it is published as a commit or pull request.
- Filesystem inspection must reject path traversal, repository escape through symlinks, and other attempts to read outside the checked-out repository.

This model is not intended to lock out legitimate development tools. Feature branches remain writable so maintainers and authorized automation can continue building and repairing Amosclaud efficiently.

## Deployment Security

Before exposing this self-hosted application to the internet:

- Set a unique `SECRET_KEY` of at least 32 characters
- Use strong database credentials
- Restrict `ALLOWED_HOSTS` to trusted origins
- Keep `DEBUG=false`
- Protect deployment and administrative endpoints with authentication and network controls
- Keep dependencies and container images updated

The example configuration contains placeholders and must not be used unchanged in production.
