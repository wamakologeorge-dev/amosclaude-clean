# Amosclaud Website Approval Backend

The GitHub Pages approval queue uses the existing Amosclaud FastAPI application as its secure control backend.

## Endpoints

- `GET /api/v1/approvals/connect?return_to=<pages-url>` creates an HttpOnly, Secure, SameSite=None approval session after the user signs in to Amosclaud.
- `GET /api/v1/approvals/status` confirms that the website approval session is active.
- `POST /api/v1/approvals/decision` records one single-use Approve or Deny decision.

## Required environment

```text
AMOSCLAUD_WEBSITE_ORIGINS=https://wamakologeorge-dev.github.io
AMOSCLAUD_COMMAND_REPOSITORY=wamakologeorge-dev/Amosclaud1
GITHUB_TOKEN_ENCRYPTION_KEY=<server-side encryption key>
GITHUB_CLIENT_ID=<GitHub OAuth app client id>
GITHUB_CLIENT_SECRET=<GitHub OAuth app secret>
GITHUB_REPOSITORY_CALLBACK_URL=https://www.amosclaud.com/api/v1/github/callback
AUTH_COOKIE_SECURE=true
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com
```

The FastAPI service must be reachable at `https://www.amosclaud.com`, matching `pages-site/control-api-config.js`.

## Security behavior

- No GitHub credential is sent to GitHub Pages JavaScript.
- The backend uses the signed-in user's encrypted GitHub authorization.
- The backend verifies `admin`, `maintain`, or `push` repository permission.
- The website origin is allowlisted.
- Every approval ID can be decided only once.
- Approval issues receive the existing `@amosclaud approve` or `@amosclaud deny` command.
- Failed workflow approvals create a scoped Amosclaud1 inspection request; they do not grant automatic publication authority.
