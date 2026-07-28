# Repository Behavior Automation

`behavior-automation.yml` adds repository behavior without granting unrestricted
write access to every job.

## Behavior

- Pull requests run the stable `behavior-quality-gate` check.
- Pull requests receive bounded area, type, size, dependency, and security labels.
- Issues receive bounded type and area labels, or `status:needs-triage`.
- A weekly maintenance run labels inactive work after 30 days. It never closes,
  merges, deletes, deploys, or rewrites repository history.
- Repository-owner manual runs may format Python files changed on a selected
  non-default branch. Direct writes to `main` are rejected.

The workflow follows the Black and isort settings already defined in
`pyproject.toml`. It installs only the formatter tools for quality and formatting
jobs; labeling and maintenance use the Python standard library and the
repository-scoped `GITHUB_TOKEN`.

## Label ownership

The automation replaces only labels it owns: `area:*`, `type:*`, `size:*`, and
`status:needs-triage`. Existing project, roadmap, priority, release, and
maintainer-created labels remain untouched. The stale label is removed whenever
new discussion activity is recorded.

## Permissions

The workflow starts with `contents: read`. Each job receives only the permissions
it needs:

- quality gate: `contents: read`;
- issue labeling: `issues: write`;
- pull-request labeling and maintenance: `issues: write` and
  `pull-requests: write`;
- owner-confirmed formatting: `contents: write` and `actions: write`.

The `pull_request_target` job never checks out or executes the contributor's head
branch. It checks out the trusted default branch and uses the GitHub API only for
labels.

## Required branch rule

After this workflow has completed successfully at least once:

1. Open **Settings → Rules → Rulesets**.
2. Create or edit the active ruleset targeting the default branch.
3. Enable **Require a pull request before merging**.
4. Enable **Require status checks to pass**.
5. Add the required check named `behavior-quality-gate`.
6. Block force pushes and branch deletion.
7. Keep bypass permissions limited to emergency administrators.

The workflow creates the check, but repository rules make that check mandatory.
It does not attempt to change its own branch rules.

## Manual formatting

From **Actions → Repository Behavior Automation → Run workflow**:

1. Select the feature branch.
2. Choose `format-branch`.
3. Enable `confirm_write`.
4. Run the workflow.

The write job rejects the default branch and non-owner actors. It formats only
Python files changed from the default branch, commits only when files changed,
then dispatches a read-only verification run for the new commit.

## Maintenance exemptions

Apply either label to prevent stale labeling:

- `status:keep-open`
- `security-sensitive`

Maintenance deliberately does not close stale issues or pull requests.
