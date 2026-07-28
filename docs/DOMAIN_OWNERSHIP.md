# Amosclaud domain ownership

The Amosclaud Autonomous, Amosclaud AI, GitHub Fixer, API, agent, and software-engineering platform use only these canonical forms:

- Full URL: `https://www.amosclaud.com/`
- Hostname: `www.amosclaud.com`

The plain domain `amosclaud.com` belongs to a separate project and must not be used as the Autonomous platform URL.

## Usage rules

Use `https://www.amosclaud.com/` for website links, API base URLs, installers, callbacks, documentation, deployment configuration, and generated links. Public API clients must connect directly over HTTPS; they must not depend on an HTTP redirect because a redirected POST can be replayed as GET and fail with HTTP 405.

Use `www.amosclaud.com` only where a hostname is required, including `CNAME`, DNS, host allowlists, and server-name configuration.

Do not automatically redirect, alias, or substitute the separate `amosclaud.com` project into Amosclaud Autonomous configuration.
