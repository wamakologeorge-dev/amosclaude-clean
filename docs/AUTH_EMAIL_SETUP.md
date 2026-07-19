# Amosclaud email authentication

Amosclaud creates accounts directly with email and password. New accounts must verify a six-digit code sent by Amosclaud. Password resets use the same email delivery system.

Set these Railway variables:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM` (for example `no-reply@amosclaud.com`)
- `SMTP_TLS=true`

For Gmail delivery, use `smtp.gmail.com`, port `587`, your Gmail address as
`SMTP_USERNAME`, and a Google App Password as `SMTP_PASSWORD`. Do not store a
normal Gmail password in the repository. The same sender delivers account
verification, password-reset, and passwordless sign-in codes.
- `AUTH_CODE_MINUTES=15`

GitHub is not an Amosclaud login provider in this flow. After signing in to Amosclaud, developers can connect GitHub from the Repositories page. Keep these variables for that integration:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL=https://amosclaud.com/api/v1/auth/github/callback`

The Railway persistent volume must remain mounted at `/data` so accounts, verification records, sessions, and repository data survive deploys.
