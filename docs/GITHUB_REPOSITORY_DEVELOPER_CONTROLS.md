# GitHub repository developer controls

Amosclaud gives the signed-in owner a safety-gated page for administering imported GitHub repositories.

## Available controls

- Update description, homepage, default branch, visibility, repository features, merge strategies, auto-merge, and branch cleanup.
- List, create, rotate, and delete GitHub Actions secrets. Secret values are encrypted with GitHub's repository public key before they are sent and are never returned by Amosclaud.
- List, create, update, and delete GitHub Actions variables.
- List, connect, update, ping, and delete HTTPS repository webhooks.
- Archive or unarchive a repository.
- Transfer a repository to another GitHub user or organization.
- Permanently delete a repository from GitHub and remove the corresponding Amosclaud workspace.

## Authorization model

Every request requires an authenticated Amosclaud session. Amosclaud then loads the user's encrypted GitHub OAuth token and verifies live `permissions.admin` access against GitHub before presenting or executing repository administration.

The normal `repo` scope supports repository settings, Actions secrets and variables, and repository webhooks. Permanent deletion additionally requires GitHub's `delete_repo` scope. The developer-settings page displays a reconnect control when that permission is missing.

Mutation requests also require the same-origin `X-Amosclaud-Intent: repository-management` header. Archive, transfer, and delete operations require the user to type the exact `owner/repository` name. Deletion requires a second irreversible-action acknowledgement.

## Secret handling

Secret inputs use Pydantic `SecretStr`, are encrypted with a Libsodium sealed box using GitHub's public key, and are sent immediately. Amosclaud does not persist the plaintext or include it in API responses or audit records. GitHub only returns secret names and timestamps.

## Audit trail

Successful mutations are recorded in `github_repository_audit_log` with the Amosclaud user, imported repository ID, GitHub full name, operation, non-secret metadata, and UTC timestamp. Secret values and webhook signing secrets are excluded.

## User interface

Open **Repositories**, choose an imported GitHub repository, and select **Developer settings**. The page is served at:

```text
/static/repository-developer-settings.html?repository_id=<id>
```

## Deployment configuration

The existing GitHub OAuth callback handles both normal connections and the elevated repository-management reconnect. `GITHUB_REPOSITORY_CALLBACK_URL` can override the generated callback URL when a deployment uses a fixed public callback address.

## Operational notes

- Repository transfers are asynchronous on GitHub. Amosclaud updates the imported repository metadata and local `origin` URL from the transfer response when GitHub returns the new full name.
- Archiving makes the GitHub repository read-only until it is unarchived.
- Deletion removes GitHub first. Amosclaud removes the local database record and workspace only after GitHub confirms success.
- Organization policy can still block transfers, deletion, visibility changes, or other administration even when the connected user is an administrator.
