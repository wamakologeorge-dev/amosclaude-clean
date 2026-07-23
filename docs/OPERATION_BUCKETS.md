# Amosclaud Operation Buckets

The Railway application and the GitHub Amosclaud Bot share one execution
contract without combining their trust boundaries:

- `www.amosclaud.com` authenticates the user, stores that user's encrypted
  GitHub authorization, creates operations, and displays verified results.
- Amosclaud Bot and Amosclaud Autonomous provide the repository execution core.
- GitHub changes are made only in repositories imported by the signed-in user
  and only with that user's GitHub authorization.
- A completed operation must include both real evidence and a deterministic
  `verification_id`. Otherwise it is recorded as failed and its reserved agent
  tokens are refunded.

## User flow

1. The user signs in and connects GitHub.
2. The platform creates one durable operation bucket for that user.
3. An imported repository, objective, execution mode, and delivery type become
   a task in that bucket.
4. The cloud runner clones the authorized repository and runs the existing
   Amosclaud Bot/Autonomous or engineering-agent path.
5. Write operations run Doctor checks, repository tests, and `git diff --check`.
6. A pull request is opened from an `amosclaud/task-*` branch when requested.
7. Artifacts, events, evidence, and the verification ID are returned to the
   same user's bucket.

## API surface

- `GET /api/v1/operations/bucket`
  returns the signed-in user's repositories, recent operations, and counts.
- `GET /api/v1/operations/bucket/events`
  returns that bucket's ordered task-event ledger.
- `POST /api/v1/tasks`
  creates an operation and assigns it to the user's bucket.
- `POST /api/v1/github/repositories/{repository_id}/issues`
  creates a real issue in an imported repository with the signed-in user's
  GitHub authorization.

The existing runner claim, approval, cancellation, completion, webhook, and
GitHub repository endpoints remain compatible. Existing tasks are assigned to
their owner's bucket lazily when that user next accesses or creates a bucket.

## UI contract

The product UI can expose only three concepts while retaining the richer
backend state:

- **Autonomous** — objective, mode, approval, and live task state.
- **Repository** — imported GitHub repositories and issue creation.
- **Results** — verified evidence, artifacts, pull requests, and event history.

`amosclaud.com` remains a separate root project. This integration targets the
Railway service deployed as `www.amosclaud.com`.
