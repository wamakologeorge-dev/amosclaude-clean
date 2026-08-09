# Amosclaud Bot formal pull-request reviews

After this change is merged to the trusted default branch, a pull-request participant can request a formal review by posting:

```text
@amosclaud review this PR
```

The `Amosclaud Bot Formal Review` workflow runs from the trusted default branch. It does not check out or execute pull-request code. It uses GitHub's API to:

1. resolve the pull request's exact head commit;
2. fetch every changed-file page;
3. fetch the exact-commit check runs;
4. produce a deterministic correctness, test, security, size, and merge-risk report;
5. re-read the pull request to detect a concurrent head change;
6. submit a GitHub pull-request review bound to the original head SHA.

## Review authority

The submitted review always uses GitHub review event `COMMENT`.

It does not:

- approve the pull request;
- submit a blocking `REQUEST_CHANGES` decision;
- merge the pull request;
- push commits;
- execute code from the pull-request branch;
- receive model-provider or GitHub App private credentials.

The review may recommend approval, human review, or changes based on its findings, but that recommendation is evidence only. Human and repository protection rules retain merge authority.

## Stale-head protection

Amosclaud reads the pull-request head before and after analysis. When the head changes during the review, it does not submit a stale formal review. It posts a short deferral message and asks for the review command to be run again against the new head.

## Verification

Focused tests prove:

- pagination includes files after the first 100;
- the GitHub review payload uses `event: COMMENT`;
- `commit_id` equals the reviewed head SHA;
- pending checks remain visible in the evidence;
- concurrent head changes prevent review publication;
- unrelated comments do not trigger a review.
