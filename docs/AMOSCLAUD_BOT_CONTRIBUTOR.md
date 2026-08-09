# Amosclaud Autonomous GitHub contributor profile

`Amosclaud Autonomous` is the single public agent identity. `Amosclaud Bot` is
the technical GitHub App attribution used for GitHub API operations, comments,
commits, branches, and pull requests. It is not a separate public product or a
human account, and it must not impersonate the repository owner.

## Public profile and technical attribution

| Field | Value |
|---|---|
| Public display name | `Amosclaud Autonomous` |
| Technical GitHub App name | `Amosclaud Bot` |
| Preferred GitHub App slug | `amosclaud-bot` |
| Expected GitHub actor | `amosclaud-bot[bot]` |
| Role | Autonomous software-engineering contributor |
| Homepage | `https://www.amosclaud.com` |
| Canonical repository | `wamakologeorge-dev/amosclaude-clean` |

Suggested public biography:

> Amosclaud Autonomous is an autonomous software-engineering contributor that inspects repositories, prepares bounded repairs, runs verification, and publishes auditable GitHub evidence.

## Permanent contributor tool policy

Every Amosclaud action and every human or automated contribution must follow
`docs/CONTRIBUTOR_TOOL_POLICY.md`
(`AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1`):

1. scan the Amosclaud repository first;
2. reuse or extend a suitable Amosclaud-owned capability;
3. introduce an external tool only after documenting the missing internal capability and the bounded exception evidence.

The contributor implementation must not remove, weaken, bypass, or make that
policy optional. The existing `Amosclaud Workflow Policy` check runs on every
pull request. Its parsed policy guard and code-owner tests reject disabled
commands, path-filtered required checks, commented ownership rules, and removed
policy markers.

## Configuration and verification levels

Configuration presence is not proof that the GitHub App works. Amosclaud keeps
three separate states:

1. `IDENTITY_CONFIGURED` means numeric App, installation, and bot user IDs are present.
2. `LIVE_AUTH_VERIFIED` means a trusted workflow authenticated as the App, minted an installation token, accessed the canonical repository, and verified the bot user ID.
3. `fully_ready` remains false until a signed production webhook delivery is also verified end to end.

The public profile command never reads the private key or webhook secret:

```bash
python -m amoscloud_ai.bot_contributor_profile
```

It reports only public identity, technical attribution, non-secret identifier
presence, and `verification_level: NOT_RUN`.

The live authentication command requires protected credentials and network
access to GitHub:

```bash
python -m amoscloud_ai.bot_contributor_profile --require-ready
```

It returns only fixed verification states and public GitHub identity metadata.
It never returns the App JWT, installation token, private key, webhook secret,
or protected file path.

## Protected workflow boundary

Pull-request code never receives the GitHub App private key or webhook secret.
The `contributor-profile-contract` job uses only non-secret repository variables
and produces a non-secret profile artifact.

After this implementation is merged to trusted `main`, a repository owner can
manually run **Amosclaud Bot Contributor** with `require_live_profile=true`.
The separate `live-profile-verification` job:

1. checks out trusted `main`, not the pull-request branch;
2. loads protected GitHub App credentials only after that checkout;
3. authenticates the App JWT against GitHub;
4. creates an installation token;
5. verifies access to `wamakologeorge-dev/amosclaude-clean`;
6. verifies the configured numeric bot user ID;
7. uploads a non-secret verification result.

This boundary prevents pull-request code from reading or exfiltrating protected
GitHub App credentials.

## Required protected values

Configure these in GitHub Actions secrets and variables, Railway, or an
equivalent protected secret manager:

```text
GITHUB_APP_SLUG=amosclaud-bot
GITHUB_APP_ID=<numeric GitHub App id>
GITHUB_APP_INSTALLATION_ID=<numeric installation id>
GITHUB_APP_BOT_USER_ID=<numeric bot account id>
GITHUB_APP_PRIVATE_KEY=<protected PEM value>
GITHUB_APP_WEBHOOK_SECRET=<exact GitHub App webhook secret>
```

`GITHUB_APP_PRIVATE_KEY_PATH` or `AMOSCLAUD_GITHUB_APP_PRIVATE_KEY` may be used
instead of `GITHUB_APP_PRIVATE_KEY` in a trusted deployment that already uses
one of those protected delivery mechanisms.

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
- receive protected App secrets while executing pull-request code;
- claim live readiness from configuration presence alone;
- claim a repair succeeded before every observed exact-commit run is evaluated;
- convert an unexpected skip, cancellation, missing check, pending check, or unresolved commit into success;
- bypass the permanent Amosclaud-first contributor tool policy.

## Owner-side activation

Repository code cannot create the GitHub App registration, upload its private
key, prove a production webhook delivery, or configure protected-branch rules.
A repository owner must:

1. create or rename the GitHub App;
2. set its public profile text and logo;
3. configure the webhook URL;
4. generate and protect the private key;
5. install the App on the intended repositories;
6. configure the protected identifiers and credentials;
7. merge the trusted contributor verifier only after approval and passing checks;
8. manually run the trusted live-profile verification;
9. send and verify a signed GitHub webhook delivery in production;
10. verify a real bot-authored comment, branch, commit, or pull request;
11. require `Amosclaud Workflow Policy / policy`, code-owner review, and no bypass for protected policy changes.

The contributor identity is not fully ready until live App authentication,
signed webhook delivery, repository action attribution, and required branch
protections are all independently verified.
