# Amosclaud as seamless developer tooling

Amosclaud is an open developer platform that connects source control, autonomous engineering tools, cloud workspaces, CI/CD, deployment, and monitoring without replacing the developer's existing workflow.

## Product contract

- Public account creation remains available through email and password.
- Developers can also use a one-time email sign-in code and password recovery from any device.
- GitHub is an optional connected developer workspace, not the only way to enter Amosclaud.
- Connecting GitHub must never delete an existing password or remove another valid sign-in method.
- Repository permissions are requested only when a developer chooses to connect source control.
- Amosclaud must keep users, sessions, encrypted source-control authorizations, repositories, and workspaces in persistent storage.

## The GitHub sibling workflow

1. A developer creates an Amosclaud account or signs in.
2. The developer connects GitHub and selects repositories they are allowed to access.
3. Amosclaud imports or clones the selected repository into an isolated workspace.
4. Autonomous tools inspect, test, diagnose, document, refactor, secure, or repair the project.
5. Amosclaud verifies the result with reproducible checks.
6. The developer can push a branch, create an issue, or open a pull request back on GitHub.
7. GitHub webhooks keep Amosclaud aware of pushes, pull requests, issues, checks, and workflow results.

GitHub remains the source-of-truth collaboration network. Amosclaud acts as the execution, verification, and automation layer beside it.

## Act as the glue

### Deep CI/CD and source-control integration

Amosclaud should support GitHub first and provide adapters for GitLab and Bitbucket. Integrations should trigger code review, test generation, build-failure diagnosis, security scanning, dependency maintenance, documentation generation, deployment, and monitoring.

### API-first architecture

Public capabilities should be available through stable REST APIs, an OpenAPI contract, and SDKs for Python, TypeScript/JavaScript, and Go. GraphQL may be added for repository, task, and organization queries where it improves developer workflows.

### Cloud-native flexibility

Developers should be able to run Amosclaud through Railway, Render, AWS, self-hosted servers, and local runners. Platform features must not depend on one hosting provider.

## Solve repetitive engineering work

Autonomous agents should handle bounded, verifiable work such as:

- diagnosing CI and build failures;
- generating and repairing tests;
- refactoring legacy code;
- reviewing pull requests;
- scanning dependencies and configuration;
- preparing documentation and release notes;
- creating reproducible preview environments;
- committing verified changes and opening pull requests.

Sensitive repair candidates that modify real secrets, personal information, private keys, or environment credentials require human approval. Ordinary repairs continue automatically.

## Developer-first growth

- Provide a useful free path for individual developers without requiring a credit card.
- Publish open-source SDKs, CLI tools, examples, starter repositories, and templates.
- Support extensions and plugins so the community can build on Amosclaud.
- Make the first successful workflow possible within five minutes.
- Publish architecture notes, build logs, technical lessons, and real repair examples.

## Nonprofit-first mission

Amosclaud may begin as a small nonprofit-oriented developer utility whose first responsibility is to help developers complete useful work. It should perform small repetitive tasks reliably, grow toward larger verified tasks, and remain transparent about what it changed, tested, and returned to the source repository.

The goal is not to imitate GitHub's scale. The goal is to become a trusted sibling utility that makes GitHub and other developer platforms more productive.
