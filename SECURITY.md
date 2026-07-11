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

Never commit API keys, tokens, passwords, private keys, or populated `.env` files. Use `.env.example` for documented placeholders and store real values in GitHub Secrets or the deployment platform's secret manager.
