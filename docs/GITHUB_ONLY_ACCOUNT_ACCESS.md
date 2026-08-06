# GitHub-only Amosclaud account access

The production Amosclaud platform uses GitHub as its only public identity provider.

## Entry routes

These routes redirect directly to GitHub OAuth:

```text
/login
/signup
/create-account
```

The OAuth start and callback routes are:

```text
/auth/github
/auth/github/callback
```

The production GitHub OAuth application must register this exact callback URL:

```text
https://www.amosclaud.com/auth/github/callback
```

## First-time signup

Any GitHub user may authorize Amosclaud. On the first successful authorization, Amosclaud creates an account using:

- the immutable GitHub numeric account ID,
- the GitHub login and display name,
- a verified primary GitHub email when available,
- or a unique internal no-reply address when the GitHub user keeps email private.

No Amosclaud password is created.

## Returning sign-in

A returning GitHub user is matched by immutable GitHub ID and receives a new Amosclaud session. A verified GitHub email may link an older Amosclaud account with the same address. A public but unverified profile email is never trusted to claim an existing account.

## Removed public authentication methods

The production gateway blocks or redirects the former public account methods:

- email and password,
- email verification codes,
- password reset,
- passkey signup and sign-in,
- Google OAuth.

Old POST authentication endpoints return HTTP 410 with `/auth/github` as the required authorization route. Old Google bookmarks redirect to GitHub.

## Owner access

Ordinary GitHub authorization never grants administrator access merely because a user belongs to a repository or organization. The separate owner-recovery callback remains restricted to the exact configured GitHub numeric ID and login.

## Hosted-tool payment boundary

GitHub signup creates the account but does not grant hosted working time. Official Amosclaud tools still require independently verified Cash App or Bitcoin organization support. Public repository source and documentation remain accessible under the published license.
