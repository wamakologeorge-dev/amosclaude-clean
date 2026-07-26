# .amosclaud

This directory is the repository-local control center for Amosclaud and is loaded before the ordinary repository `.env`, application settings, database initialization, and API router registration.

Startup order:

1. Operating-system, Railway, and container environment variables remain authoritative.
2. `.amosclaud/startup.json` declares the repository control load order.
3. Listed `.amosclaud` environment files provide repository-local defaults.
4. Listed policy manifests are validated and exposed as startup evidence.
5. The ordinary repository `.env` fills only values that are still unset.
6. Amosclaud application initialization continues.

Current responsibilities:

- repository identity and configuration
- startup precedence and environment defaults
- professional pull request review policy
- Autonomous/Fixer behavior boundaries
- future bot permissions, review rules, and verification policy

Server startup never automatically runs mutating scripts from this directory. Repair, commit, force-push, and deployment programs require an explicit bounded operation with their normal verification and authorization controls.

Amosclaud Bot remains GitHub-native and does not require the Amosclaud website to operate.
