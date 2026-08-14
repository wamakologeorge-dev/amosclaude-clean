# Amosclaud domain ownership

The Amosclaud Autonomous, Amosclaud AI, GitHub Fixer, API, agent, and software-engineering platform use only these canonical forms:

- Full URL: `https://amosclauds.com/`
- Hostname: `amosclauds.com`

The legacy domains `amosclaud.com` and `www.amosclaud.com` belong to a separate,
unrelated project and must not be used as the Autonomous platform URL. Any
configuration still pointing at those legacy hosts is normalised forward to
`https://amosclauds.com`.

## Usage rules

Use `https://amosclauds.com/` for website links, API base URLs, installers, callbacks, documentation, deployment configuration, and generated links. Public API clients must connect directly over HTTPS; they must not depend on an HTTP redirect because a redirected POST can be replayed as GET and fail with HTTP 405.

Use `amosclauds.com` only where a hostname is required, including `CNAME`, DNS, host allowlists, and server-name configuration.

Do not automatically redirect, alias, or substitute the separate `amosclaud.com` / `www.amosclaud.com` project into Amosclaud Autonomous configuration.
