# Amosclaud email authentication

Amosclaud creates accounts directly with email and password. New accounts must verify a six-digit code sent by Amosclaud. Password resets use the same email delivery system.

Set these Railway variables:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM` (for example `no-reply@amosclaud.com`)
- `SMTP_TLS=true`
- `AUTH_CODE_MINUTES=15`

GitHub is not an Amosclaud login provider in this flow. After signing in to Amosclaud, developers can connect GitHub from the Repositories page. Keep these variables for that integration:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL=https://amosclaud.com/api/v1/auth/github/callback`

The Railway persistent volume must remain mounted at `/data` so accounts, verification records, sessions, and repository data survive deploys.
