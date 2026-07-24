# Railway persistent storage

Amosclaud stores password hashes, login sessions, users, and native repositories in SQLite and the repository filesystem.

The production container now uses:

- `AUTH_DB_PATH=/data/auth.db`
- `REPOSITORY_STORAGE_PATH=/data/repositories`

A Railway Volume must be mounted at `/data`. Without a mounted volume, Railway replaces the container filesystem during redeploys and the user database is lost. That causes previously correct passwords to return `Invalid email or password` and resets the native repository list.

## Railway setup

1. Open the Amosclaud service in Railway.
2. Open **Settings** or **Volumes**.
3. Add a persistent volume.
4. Set its mount path to `/data`.
5. Redeploy the service.
6. Create the account one final time if the old ephemeral database has already been removed.

After the volume is mounted, future deployments will keep users, password hashes, sessions, and native repositories.
