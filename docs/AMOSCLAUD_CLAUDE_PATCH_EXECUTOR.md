# Amosclaud Claude Patch Executor

**Contract:** `AMOSCLAUD-CLAUDE-PATCH-CONTRACT:v1`

The Claude Patch Executor is an optional backup lane for owner-authorized pull-request changes. It extends Amosclaud's existing parser, patch validation, repair memory, credential-free verifier, and GitHub App connection. It does not replace the native Amosclaud Fixer.

## Command

Post this comment on an open pull request whose head branch belongs to the same repository:

```text
@amosclaud patch <bounded engineering objective>
```

The aliases `@amosclaud ai-fix ...` and `@amosclaud claude-fix ...` select the same lane.

Normal `@amosclaud fix ...` commands and structured owner directives remain on Amosclaud's native fixer path. This prevents two repair engines from racing on one comment.

## Required configuration

Repository variables:

```text
ANTHROPIC_MODEL=<owner-selected Claude model identifier>
ANTHROPIC_BASE_URL=https://api.anthropic.com
GITHUB_APP_SLUG=amosclaud-bot
GITHUB_APP_ID=<numeric app id>
GITHUB_APP_INSTALLATION_ID=<numeric installation id>
GITHUB_APP_BOT_USER_ID=<numeric bot account id>
```

Repository secrets:

```text
ANTHROPIC_API_KEY=<dedicated Anthropic API key>
GITHUB_APP_PRIVATE_KEY=<GitHub App private key>
```

The model identifier is intentionally owner-configured rather than hardcoded to a moving alias.

## Trusted execution boundary

The workflow checks out trusted default-branch code into `trusted/` and checks out the exact pull-request head into `target/`. Pull-request code is treated as untrusted input and is never executed while the Claude key or GitHub App private key is available.

The sequence is:

1. `.github/scripts/parse_comment.py` classifies the comment and stores the objective locally.
2. GitHub metadata resolves the exact PR head SHA, base SHA, source repository, and branch.
3. Fork and closed-PR publication are rejected.
4. `.github/scripts/ai_patch_executor.py` sends bounded, secret-filtered repository context to the Anthropic Messages API.
5. The executor accepts only one unified Git diff, validates paths and size using the existing Amosclaud repair policy, and runs `git apply --check`.
6. A separate step applies the artifact and verifies that the actual changed-file set exactly matches the validated report.
7. Amosclaud's credential-free repair verifier runs without the Claude key or GitHub App credentials.
8. Only after verification does the trusted GitHub App connection mint a short-lived installation token.
9. The workflow rechecks the remote PR head SHA, commits only reported files, and performs a normal non-force push to the same PR branch.
10. All ordinary CI, security, policy, code-owner, and review requirements still apply.

## Codebase context

The Claude request receives a bounded context containing:

- a tracked source-file inventory;
- the pull-request diff summary;
- changed files and objective-relevant source excerpts;
- repository operating instructions;
- verified Amosclaud repair-memory hints;
- the owner objective and request evidence as untrusted data.

The context builder excludes `.env` files, credential files, private keys, common build/vendor directories, and unsupported binary formats. It limits both the file count and total character count.

## Authority boundaries

The Claude executor cannot:

- apply its own patch;
- execute target repository code;
- commit or push;
- approve or merge a pull request;
- force-push;
- write to the default branch;
- access the GitHub App private key;
- publish when the PR head moved;
- bypass Amosclaud's repair policy or sensitive-data controls.

The publication workflow cannot publish unless generation, patch validation, exact changed-file matching, credential-free verification, GitHub App authentication, repository-access verification, bot-identity verification, and stale-head protection all pass.

## Evidence

Every attempt uploads a fourteen-day evidence artifact containing the public command metadata, request evidence, diff artifact, candidate report, and verification report. Secret values and installation tokens are not included.
