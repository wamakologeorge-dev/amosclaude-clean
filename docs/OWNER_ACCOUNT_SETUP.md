# Owner account setup

Amosclaud owner access is configured with environment variables. Do not commit passwords or private credentials to the repository.

## Multiple owner accounts

Set `AMOSCLAUD_OWNER_EMAILS` to a comma-separated list of trusted administrator emails:

```text
AMOSCLAUD_OWNER_EMAILS=georgekbbito@gmail.com,wamakologeorge@gmail.com
```

For backward compatibility, `AMOSCLAUD_ADMIN_EMAIL` is still supported when `AMOSCLAUD_OWNER_EMAILS` is not set.

Each listed email must correspond to an existing Amosclaud administrator account. After changing the value, restart the service and sign in again.

## Passwords

Passwords must be created or changed through the authentication system and stored only as password hashes. Never place a plaintext password in source code, Git history, configuration committed to the repository, or browser JavaScript.
