# Amosclaud Product and Plan Specification

Version 1.0 — Draft for product and legal review

## Product summary

Amosclaud is a developer platform that connects to authorized GitHub accounts and organizations. Users can create repositories, upload files, create branches and pull requests, run code-health checks, and ask the Amosclaud AI Agent to diagnose and prepare fixes.

## Subscription plans

| Plan | Price | Trial | AI Agent | Primary access |
|---|---:|---|---|---|
| Trial | $0 | 15 days | Enabled for evaluation | Limited platform evaluation |
| Developer | $29/month | No | Disabled | Repositories, files, branches, pull requests, manual tests |
| Pro | $100/month | No | Enabled | Developer features plus AI diagnosis and fixes |
| Enterprise | Displayed or quoted separately | Custom | Enabled | Organizations, governance, and enterprise controls |

Developer users cannot use the AI Agent. The Agent interface must remain disabled and show an upgrade message until the user upgrades to Pro or Enterprise.

## Conversational Agent experience

The signed-in user talks to one Amosclaud chatbot. The Agent uses the verified account name in its greeting.

Example after sign-in:

> Hi, George Makulu. What do you want to build today?

When the user gives an incomplete instruction such as `Build`, the Agent replies:

> What would you like to build today, George Makulu?

When the user gives a simple instruction such as `Build a login page`, the Agent asks a useful clarifying question before modifying code:

> I can help with that. Should the login page use email and password, GitHub sign-in, Google sign-in, or all three?

The Agent keeps the entire conversation in the same chat window, follows instructions in sequence, and does not begin code changes until it has enough information or receives confirmation.

## Three-AI support team in one chatbot

The user sees only one chatbot. The main Amosclaud Agent coordinates three specialized AI helpers behind the scenes:

- **Builder AI** plans and writes code, creates project structure, uploads or edits files, and prepares implementation changes.
- **Tester AI** runs code-health checks, tests, linting, and security checks, then explains failures.
- **Reviewer AI** reviews proposed changes, checks pull requests, identifies risks, and verifies that the work matches the user's request.

The main Agent combines all helper results into one response. The multi-agent feature is disabled on Developer and enabled on Pro and Enterprise.

## GitHub and organization capabilities

Users can:

- connect a personal GitHub account;
- list repositories they are authorized to access;
- list organizations that installed or authorized Amosclaud;
- create a real repository under their account or an authorized organization;
- upload files and folders to a selected repository;
- create branches, commits, and pull requests;
- view pull-request status, checks, comments, and changed files;
- run code-health checks manually;
- ask the Agent to diagnose failures and prepare fixes;
- have the Agent create a working branch and open a pull request.

Access is permission-based. Amosclaud cannot automatically access every organization. An organization owner must install or approve the integration and may limit it to selected repositories.

## Safe Agent workflow

1. The user selects an authorized repository.
2. The Agent asks what the user wants to build, test, or fix.
3. The Agent creates a working branch.
4. Builder AI uploads or edits files on that branch.
5. Tester AI runs tests and code-health checks.
6. Reviewer AI reviews the proposed changes and risks.
7. The main Agent shows the combined result.
8. The user confirms.
9. The Agent commits changes and opens a pull request.

## Actions requiring explicit confirmation

- Merging a pull request.
- Pushing directly to a protected default branch.
- Deleting a repository or organization resource.
- Changing organization permissions or settings.
- Production deployment.
- Destructive database changes.
- Account deletion.

## Account features

- Create an account and sign in.
- Sign in with email and password.
- Sign in with GitHub.
- Sign in with Google.
- Link matching verified emails to one account rather than create duplicates.
- Log out and log out of all devices.
- Recover a forgotten password.
- Recover a forgotten email using verified recovery information.
- Delete an account with confirmation.
- Recover an account during the published recovery period.

## Feature gating

| Feature | Developer | Pro | Enterprise |
|---|---|---|---|
| Repository creation | Enabled | Enabled | Enabled |
| File upload | Enabled | Enabled | Enabled |
| Branches and pull requests | Enabled | Enabled | Enabled |
| Manual code-health tests | Enabled | Enabled | Enabled |
| AI Agent chat | Disabled | Enabled | Enabled |
| Builder, Tester, and Reviewer AIs | Disabled | Enabled | Enabled |
| AI diagnosis and fix preparation | Disabled | Enabled | Enabled |
| Organization governance controls | Limited | Standard | Enterprise controls |

## Acceptance criteria

- Developer users see the AI Agent locked and receive an upgrade prompt.
- Pro and Enterprise users can use the unified Agent conversation.
- The Agent uses the signed-in user's verified profile name.
- Repository and organization lists show only authorized resources.
- The product presents one chatbot, not four separate chatbot interfaces.
- The main Agent can delegate work to Builder AI, Tester AI, and Reviewer AI.
- The main Agent combines helper results into one response.
- All code fixes are made on a branch and proposed through a pull request.
- Destructive and production actions require confirmation.
- Account recovery and deletion flows are available and auditable.

## Legal notice

The commercial-license language is a draft and should be reviewed by qualified legal counsel before public release.
