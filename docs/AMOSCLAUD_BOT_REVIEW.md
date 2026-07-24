# Amosclaud Bot — Professional Pull Request Review

Use the following command in a pull request conversation:

```text
@amosclaud review this PR
```

Amosclaud Bot runs from the checked-out repository through GitHub Actions and routes the review through Amosclaud Autonomous.

The professional review reports:

- pull request summary and branch direction
- changed-file and diff-size context
- HIGH / MEDIUM / LOW findings
- security-sensitive path changes
- whether changed tests accompany source changes
- Autonomous runtime status and evidence
- a final recommendation: APPROVE, NEEDS HUMAN REVIEW, or CHANGES REQUESTED

Review mode is read-only. Repository writes remain restricted to trusted collaborator requests using:

```text
@amosclaud fix <specific problem>
```

Professional review policy is kept under `.amosclaud/review.yml` so the repository-visible Amosclaud configuration remains the control center for the bot.
