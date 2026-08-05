# Reliable Amosclaud account access

Amosclaud supports account creation, password and email-code sign-in, current-device sign-out, all-device sign-out, password recovery, GitHub linking, and self-service account deletion.

## Required production settings

Use one canonical HTTPS origin and configure the authentication service consistently:

```env
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_DOMAIN=.amosclaud.com
AUTH_SESSION_DAYS=7
AUTH_DB_PATH=/data/auth.db
```

`AUTH_COOKIE_DOMAIN=.amosclaud.com` lets a verified session work on both `amosclaud.com` and `www.amosclaud.com`. The sign-in page calls the protected session-sharing endpoint after successful password, email-code, passkey, or registration verification.

## Persistent account storage on Railway

The current authentication store is SQLite. Run one application replica and mount a persistent Railway volume at `/data`, then set `AUTH_DB_PATH=/data/auth.db`.

Without a persistent volume, redeployments can replace the local database and remove users or sessions. Multiple replicas must not use separate local SQLite files because requests can reach different account stores.

Before scaling to multiple application replicas, move the authentication tables and sessions to a shared transactional database such as PostgreSQL.

## Public and private access

- `/status` is public and read-only.
- `/api/v1/public/status` returns a redacted status summary without accounts, private repositories, secrets, or task logs.
- `/login` supports sign-in and account creation.
- `/account`, `/cloud/agent`, `/repositories`, and workspaces require a valid session.
- `/admin` remains administrator-only.

## Account lifecycle

Signed-in users can open `/account` to:

- review their profile;
- sign out the current browser;
- revoke all sessions on all devices;
- open available account tools;
- permanently delete their account after explicit email and password confirmation.
