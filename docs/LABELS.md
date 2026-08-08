# Issue and Pull Request Labels

Amosclaud uses a composable label taxonomy. A normal issue or pull request should usually receive one label from each relevant group rather than one long custom label.

The canonical definitions live in [`.github/labels.yml`](../.github/labels.yml).

## Label groups

### Area

Area labels identify the part of the ecosystem that owns the work:

```text
area:backend
area:frontend
area:pipeline
area:runtime
area:java-pod
area:observability
area:github
area:security
area:docs
area:infrastructure
area:agent
area:legacy
```

Use more than one area only when the change genuinely crosses those boundaries. `area:legacy` does not mean “safe to ignore.” It marks a compatibility surface that must continue participating in the shared ecosystem.

### Type

Type labels describe the nature of the change:

```text
type:bug
type:feature
type:docs
type:refactor
type:test
type:security
type:maintenance
```

A bug report should not be labeled `type:bug` until the behavior is reproduced or supported by clear evidence. New reports can begin with `status:needs-triage`.

### Size

Size labels describe expected review surface, not importance:

```text
size:xs
size:s
size:m
size:l
size:xl
```

`size:xl` is a warning that the change should normally be split into smaller, independently verifiable pull requests.

### Priority

Priority labels describe urgency and impact:

```text
priority:p0
priority:p1
priority:p2
priority:p3
```

- `priority:p0`: production outage, active security exposure, data-loss risk, or equivalent emergency;
- `priority:p1`: blocks an important user or platform path;
- `priority:p2`: normal planned work;
- `priority:p3`: useful improvement without immediate urgency.

### Status

Status labels describe the next action:

```text
status:needs-triage
status:needs-evidence
status:blocked
status:needs-review
status:changes-requested
status:ready-to-merge
status:waiting-for-approval
```

`status:ready-to-merge` does not merge a pull request and does not override the repository owner's decision. It means the expected review and checks are complete.

### Community and compatibility

```text
good first issue
help wanted
breaking-change
```

A `good first issue` must have a focused scope, clear acceptance criteria, and enough context for a contributor who is new to Amosclaud.

## Examples

A failed Java build that can be reproduced:

```text
area:java-pod
type:bug
size:s
priority:p1
status:needs-review
```

A proposal for new PipeFail timeline graphics:

```text
area:observability
area:pipeline
type:feature
size:m
priority:p2
status:needs-triage
```

A protected production deployment change waiting for the owner:

```text
area:infrastructure
type:maintenance
size:m
priority:p1
status:waiting-for-approval
```

## Synchronizing labels

The repository includes a manual workflow named **Sync Repository Labels**.

1. Open the repository's **Actions** tab.
2. Select **Sync Repository Labels**.
3. Run it with `dry_run: true` first.
4. Review the reported create and update operations.
5. Run it again with `dry_run: false` to apply the canonical labels.

The workflow is intentionally manual and additive:

- it creates missing labels;
- it updates the color or description of labels listed in the manifest;
- it does not delete labels that are not listed;
- it does not relabel existing issues or pull requests;
- it uses the workflow-scoped GitHub token and requests only `contents: read` and `issues: write`.

Local manifest validation without GitHub access:

```bash
python -m pip install PyYAML==6.0.2
python scripts/ci/sync_github_labels.py --dry-run
```

The no-token dry run validates label names, unique entries, six-digit colors, and GitHub's description-length limit without making a network request.

## Triage sequence

For a new issue:

1. add `status:needs-triage`;
2. identify the owning `area:*` label;
3. request logs, reproduction steps, screenshots, or test evidence when needed;
4. assign `type:*`, `size:*`, and `priority:*` after the scope is understood;
5. replace `status:needs-triage` with the next actionable status.

Do not use labels to claim that work is fixed, verified, deployed, or safe when the supporting checks have not run.
