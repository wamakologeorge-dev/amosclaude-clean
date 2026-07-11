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

## Deployment Security

Before exposing this self-hosted application to the internet:

- Set a unique `SECRET_KEY` of at least 32 characters
- Use strong database credentials
- Restrict `ALLOWED_HOSTS` to trusted origins
- Keep `DEBUG=false`
- Protect deployment and administrative endpoints with authentication and network controls
- Keep dependencies and container images updated

The example configuration contains placeholders and must not be used unchanged in production.
