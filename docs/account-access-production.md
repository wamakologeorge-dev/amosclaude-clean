# Reliable Amosclaud account access

Amosclaud supports account creation, password and email-code sign-in, current-device sign-out, all-device sign-out, password recovery, optional GitHub linking, and self-service account deletion.

## Required production settings

Use the canonical Amosclaud HTTPS origin consistently:

```env
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_DOMAIN=
AUTH_SESSION_DAYS=7
AUTH_DB_PATH=/data/auth.db
REPOSITORY_STORAGE_PATH=/data/repositories
```

`AUTH_COOKIE_DOMAIN` must remain empty. That creates a host-only cookie for `www.amosclaud.com` and prevents the separate `amosclaud.com` platform from receiving Amosclaud sessions.

## Persistent account storage on Railway

The current authentication and GitHub-connection store uses SQLite. Run one application replica and mount a persistent Railway Volume at `/data`.

The volume preserves:

- user accounts and password hashes;
- email verification and recovery state;
- login sessions;
- encrypted GitHub account authorizations;
- imported repository metadata;
- repository workspace files.

Without the volume, a Railway redeployment can replace the local database and make an existing account or GitHub connection appear to have been removed. GitHub Client IDs and secrets configure the integration but do not preserve user connection records.

Use one stable `GITHUB_TOKEN_ENCRYPTION_KEY` in Railway. Rotating or removing it makes previously stored GitHub authorizations unreadable and requires users to reconnect GitHub.

Multiple replicas must not use separate local SQLite files because requests can reach different account stores. Before scaling to multiple application replicas, move accounts, sessions, and connection records to a shared transactional database such as PostgreSQL.

## Public and private access

- `/status` is public and read-only.
- `/api/v1/public/status` returns a redacted status summary without accounts, private repositories, secrets, or task logs.
- `/login` supports sign-in and account creation.
- `/auth/github` is an optional identity-provider route.
- `/account`, `/cloud/agent`, `/repositories`, and workspaces require a valid Amosclaud session.
- `/api/v1/github/connect` begins explicit repository authorization after sign-in.
- `/admin` remains administrator-only.

## Account lifecycle

Signed-in users can open `/account` to:

- review their profile;
- sign out the current browser;
- revoke all sessions on all devices;
- connect or reconnect GitHub;
- open available account tools;
- permanently delete their account after explicit email confirmation and, for password-backed accounts, password confirmation.
