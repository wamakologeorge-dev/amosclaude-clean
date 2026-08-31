# Amosclaud Word Book

Status: **implemented / verification pending**

The Amosclaud Word Book is a shared engineering-memory product for humans and agents. It is not a replacement name for `README.md`. README remains the repository introduction; the Book holds chapter-oriented product context, capability truth, change reports, agent handoff context and the completion gate.

## Two-way design

The canonical portable representation lives at `.Amosclaud/book/` as JSON, JSONL and Markdown. This makes it Git-native: normal repository history can version, diff, review and distribute it. `amoscloud_ai.book.AmosclaudBook` reads and writes the same contract directly, which makes it Amosclaud-native without requiring the GitHub API. A future direct Amosclaud/MCP connection can consume the service contract and synchronize repository representation without redesigning the Book.

```text
Git repository/history
        ↕
.Amosclaud/book
        ↕
AmosclaudBook service
        ↕
/api/v1/book/*
   ↙           ↘
human reader   agents/MCP/connectors
```

GitHub is therefore one versioning/synchronization path, not the only runtime path.

## Human reading surface

The reader is served at `/api/v1/book/reader`. It presents chapter navigation in a document-style interface, shows capability truth, targets roughly three minutes per chapter, and provides a **Finish chapter** action. Reading completion is stored separately from engineering verification and does not prove a capability works.

## Agent surface

The native API includes:

- `GET /api/v1/book`
- `GET /api/v1/book/status`
- `GET /api/v1/book/chapters`
- `GET /api/v1/book/chapters/{chapter_id}`
- `POST /api/v1/book/chapters/{chapter_id}/complete`
- `GET /api/v1/book/products/{product_id}`
- `GET /api/v1/book/capabilities`
- `GET /api/v1/book/changes`
- `POST /api/v1/book/changes`
- `GET /api/v1/book/next-task`
- `POST /api/v1/book/agent-context`
- `POST /api/v1/book/gate`

An agent context is a versioned Book snapshot containing the relevant chapters, capability registry, next task and the Book version consumed by the agent. It avoids uncontrolled full-book copies while preserving the requirement that each agent receives an identifiable copy/context.

## Mandatory change contract

A meaningful Amosclaud change follows this lifecycle:

```text
inspect Book
  ↓
make controlled change
  ↓
execute tests/checks
  ↓
record verification truth
  ↓
update chapter/capability/change ledger
  ↓
Book Gate
  ↓
eligible for completion/merge
```

`.github/workflows/amosclaud-book-gate.yml` checks pull-request diffs and rejects meaningful changes that do not update `.Amosclaud/book/`. It also runs the dedicated Book tests. For GitHub to make the check absolutely merge-blocking, repository branch/ruleset configuration must require the `Book change contract` status check. The existence of the workflow alone is not represented as proof that branch protection is configured.

Amosclaud-native agents should call the same gate contract before exposing a merge/completion action. The platform-level policy is intentionally independent from GitHub so the same rule can later govern direct Amosclaud work.

## Truth states

The Book uses `verified`, `implemented_verification_pending`, `in_progress`, `planned`, `blocked`, and `not_available`. A commit, PR, merge or deployment is never automatically translated to `verified`.

## Security

Book files must not contain passwords, private keys, bearer tokens, recovery codes or other recoverable secrets. Agent context gives knowledge, not authority. Actual platform authentication and authorization remain responsible for privileged actions.

## Verification

Dedicated tests are in `tests/test_amosclaud_book.py`. Until CI or another observed execution proves those tests pass on the current revision, this document remains **implemented / verification pending**.
