# Amosclaud Standalone Repository Platform

Amosclaud is the system of record for software projects created on the platform. Normal repository work must not require GitHub, GitLab, Bitbucket, or another hosted source-control provider.

## Native capabilities

Every Amosclaud repository provides:

- Git-backed source storage on Amosclaud-managed persistent storage.
- Repository creation, deletion, visibility, collaborators, and access control.
- Branch creation and branch browsing.
- File tree browsing, file reading, file creation, editing, moving, and deletion.
- Commits with the authenticated Amosclaud user's name and email.
- Native issues stored in the Amosclaud database.
- Native pull requests between branches in the same Amosclaud repository.
- Native no-fast-forward merges with conflict protection.
- Repository-owned deployment settings stored at `.amosclaud/deployment.json`.
- Project-owned automation and CI settings under `.amosclaud/`.
- Source folders under `src/` and verification under `tests/`.

## Source-of-truth rule

The repository source and its `.amosclaud/` configuration are authoritative. External integrations may be added later as optional mirrors or import/export tools, but they must never be required for creating repositories, editing files, committing, opening issues, opening pull requests, merging, testing, or deploying.

## Required project structure

```text
project/
├── .amosclaud/
│   ├── deployment.json
│   └── workflow.yml
├── src/
├── tests/
└── README.md
```

## Pull-request safety

A native pull request must:

1. Use two different existing branches.
2. Contain different commits.
3. Remain open until merged or closed.
4. Refuse duplicate open requests for the same head and base.
5. Abort cleanly when Git reports a merge conflict.
6. Record the resulting merge commit in Amosclaud.

## Deployment configuration

Deployment settings belong inside the repository and are committed like source code. The native configuration includes provider, build command, start command, health-check path, environment-name references, and automatic deployment branch.

Secrets are never written into repository configuration. Secret values belong in Amosclaud's protected secret store and configuration files may contain only secret names or references.

## User experience

A user should be able to complete the entire development lifecycle from Amosclaud:

1. Create a repository.
2. Organize folders and files.
3. Edit source code.
4. Add and run tests.
5. Create a branch.
6. Commit changes.
7. Open a real issue.
8. Open a native pull request.
9. Review and merge it.
10. Configure and run deployment.

GitHub is not part of this required path.
