# Amosclaud Bot contributor profile

Amosclaud Bot is the GitHub App identity used for autonomous repository work.
It is not a human account and must not impersonate the repository owner.

## Public profile

| Field | Value |
|---|---|
| Display name | `Amosclaud Bot` |
| Preferred GitHub App slug | `amosclaud-bot` |
| Expected GitHub actor | `amosclaud-bot[bot]` |
| Role | Autonomous software-engineering contributor |
| Homepage | `https://www.amosclaud.com` |
| Canonical repository | `wamakologeorge-dev/amosclaude-clean` |

Suggested public biography:

> Amosclaud Bot is an autonomous software-engineering contributor that inspects repositories, prepares bounded repairs, runs verification, and publishes auditable GitHub evidence.

## Contributor readiness contract

The profile is **READY** only when all of these non-secret facts are true:

- a GitHub App ID is configured;
- a GitHub App private key or protected private-key path is configured;
- the installation ID for the target GitHub account is configured;
- the numeric GitHub bot user ID is configured for commit attribution;
- the GitHub App webhook secret is configured.

The application exposes only Boolean readiness and missing configuration names.
It never returns the private key, webhook secret, installation token, or file path.

Run the local profile report:

```bash
python -m amoscloud_ai.bot_contributor_profile
```

Require complete readiness:

```bash
python -m amoscloud_ai.bot_contributor_profile --require-ready
```

## Required deployment variables

Configure these in the protected Railway service environment or an equivalent
secret manager:

```text
GITHUB_APP_SLUG=amosclaud-bot
GITHUB_APP_ID=<numeric GitHub App id>
GITHUB_APP_INSTALLATION_ID=<numeric installation id>
GITHUB_APP_BOT_USER_ID=<numeric bot account id>
GITHUB_APP_PRIVATE_KEY=<protected PEM value>
GITHUB_APP_WEBHOOK_SECRET=<exact GitHub App webhook secret>
```

`GITHUB_APP_PRIVATE_KEY_PATH` or `AMOSCLAUD_GITHUB_APP_PRIVATE_KEY` may be used
instead of `GITHUB_APP_PRIVATE_KEY` when the deployment already uses one of
those protected delivery mechanisms.

## Commit attribution

When the bot user ID is configured, Amosclaud derives this no-reply address:

```text
<BOT_USER_ID>+amosclaud-bot[bot]@users.noreply.github.com
```

Repository automation should use:

```text
user.name  = Amosclaud Bot
user.email = the derived no-reply address
```

An installation token must authenticate the push or GitHub API operation. A
local Git author name alone does not prove that the GitHub App performed the
action.

## Safety boundaries

Amosclaud Bot must never:

- push directly to a protected default branch;
- force-push;
- merge without the repository's explicit approval gate;
- expose credentials or protected environment values;
- claim a repair succeeded before required checks complete;
- convert an unexpected skip, cancellation, missing check, or pending check into success.

## Owner-side activation

Repository code cannot create the GitHub App registration or upload its private
key. A repository owner must:

1. create or rename the GitHub App;
2. set the public profile text and logo;
3. configure the webhook URL;
4. generate and protect the private key;
5. install the App on the intended repositories;
6. copy only the required protected values into Railway;
7. run the contributor verification workflow;
8. verify a real bot-authored comment, branch, commit, or pull request.

The profile is not considered live until that end-to-end action is visible on
GitHub under the App's bot actor.
