# Google Sign-In for Amosclaud

Amosclaud uses Google OpenID Connect through a server-side OAuth authorization-code flow. The browser never receives the Google client secret, and Amosclaud stores no Google access or refresh tokens.

## Google Cloud configuration

1. Open Google Cloud Console and select the production project.
2. Open **Google Auth Platform** (or **APIs & Services > OAuth consent screen** in the older navigation).
3. Set the audience to **External** for public Google accounts.
4. While testing, add every permitted account under **Test users**.
5. For public access, change the publishing status from **Testing** to **In production**.
6. Request only these scopes:
   - `openid`
   - `email`
   - `profile`
7. Complete the app name, support email, developer contact, homepage, privacy-policy URL, and authorized domain for `amosclaud.com`.

The three sign-in scopes above do not grant access to Gmail, Drive, Calendar, or other sensitive Google API data. Google may still require brand verification before a custom app name or logo is broadly displayed.

## OAuth client

Create an OAuth client with application type **Web application**.

Configure this exact Authorized redirect URI:

```text
https://www.amosclaud.com/api/v1/auth/google/callback
```

The value must match `GOOGLE_CALLBACK_URL` character for character, including scheme, host, path, and absence of a trailing slash.

The current implementation is server-side and does not require Authorized JavaScript Origins. They may still be registered for a future Google Identity Services browser widget:

```text
https://amosclaud.com
https://www.amosclaud.com
```

## Deployment variables

Configure these values in Railway, Docker, or the deployment secret manager:

```text
GOOGLE_CLIENT_ID=<web-client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<web-client-secret>
GOOGLE_CALLBACK_URL=https://www.amosclaud.com/api/v1/auth/google/callback
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com/
AUTH_COOKIE_SECURE=true
```

Never commit the real client secret.

## Runtime behavior

The login page checks `GET /api/v1/auth/google/status` and only displays the Google button when both credentials are configured.

The browser starts sign-in at:

```text
GET /api/v1/auth/google
```

Google returns to:

```text
GET /api/v1/auth/google/callback
```

Amosclaud then:

1. Verifies the one-time OAuth state cookie.
2. Exchanges the authorization code directly with Google.
3. Reads the OpenID Connect user profile from Google.
4. Requires a stable Google subject and a verified email address.
5. Reuses an existing linked Google identity when present.
6. Links an existing Amosclaud account with the same verified email, or creates a new account just in time.
7. Assigns the normal first-user/admin policy and creates the regular `amos_session` cookie.
8. Redirects the user to `/cloud/agent`.

Google tokens are used only during the callback and are not persisted.

## Troubleshooting

### `redirect_uri_mismatch`

Confirm that the Google Cloud redirect URI and `GOOGLE_CALLBACK_URL` are exactly:

```text
https://www.amosclaud.com/api/v1/auth/google/callback
```

### Only selected accounts can sign in

The OAuth audience is still in Testing mode. Add the account as a test user or publish the app to production.

### Google button is not visible

Call `/api/v1/auth/google/status`. The response must report `enabled: true`. Confirm both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are present in the running service, then redeploy.

### Session disappears after callback

Confirm production is HTTPS and set:

```text
AUTH_COOKIE_SECURE=true
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com/
```
