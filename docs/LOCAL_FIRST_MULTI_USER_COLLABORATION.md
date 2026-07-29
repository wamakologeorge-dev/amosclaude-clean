# Local-first multi-user collaboration model

Amosclaud is designed to support two complementary operating modes:

1. **sovereign local installations**, where a person or organization controls its own runtime, data, credentials, and AI services; and
2. **coordinated cloud services**, where amosclaud.com can provide shared identity, organization management, billing, discovery, and deployment coordination without requiring every private workspace to move into one central runtime.

The local installation remains a complete operating boundary. Cloud coordination should extend it, not silently take ownership of local files, secrets, models, or execution privileges.

## Current foundation

The repository already contains authenticated account and organization foundations. Current organization support includes:

- authenticated organization creation;
- unique organization names and paths;
- membership roles for `owner`, `admin`, `developer`, and `viewer`;
- administrator-controlled member assignment;
- attachment of repositories to an organization;
- membership and repository-ownership checks before organization changes.

These capabilities establish the authorization model, but they do not yet represent a complete enterprise collaboration product. Team subdivisions, invitations, shared billing, audit exports, policy inheritance, synchronized cloud execution, and cross-installation presence remain future work.

## Independent local installations

A normal Amosclaud installation may run on a developer workstation, Chromebook Linux environment, local server, private virtual machine, or dedicated container host.

Each installation should own its own:

- user database and local sessions;
- repository storage and Git history;
- Redis queues and task state;
- API tokens, model credentials, GitHub credentials, and encryption keys;
- local AI models and model-provider configuration;
- workspace containers, command policies, and resource limits;
- logs, artifacts, indexes, and private knowledge.

This creates a sovereign environment. Another Amosclaud installation cannot read or operate that environment merely because both installations use amosclaud.com or collaborate on the same GitHub repository.

### Trust boundary

Local secrets must remain local unless a user explicitly configures a trusted remote service. Git synchronization transfers committed repository content; it must not be treated as a mechanism for synchronizing `.env` files, databases, runtime tokens, uncommitted work, terminal history, or private task logs.

The private Node.js control plane follows this model. It is deployed per installation, uses a private bearer token, stores its queue state in that installation's Redis service, and receives only the repository storage required by its worker.

## Collaboration available today

Developers can collaborate immediately without sharing one runtime:

```text
Developer A installation                 Developer B installation

local repository                         local repository
local Amosclaud agents                    local Amosclaud agents
local secrets and models                  local secrets and models
        │                                         │
        └──── commit / push ── GitHub ── pull ────┘
```

A practical workflow is:

1. A repository owner creates or selects a shared GitHub repository.
2. Each collaborator clones it into their own Amosclaud installation.
3. Each installation runs its own agents, builds, tests, and local verification.
4. Contributors create branches and commits locally.
5. Changes are exchanged through pull requests, reviews, protected branches, and normal Git synchronization.
6. Deployment credentials and production access remain separately governed.

This model gives collaborators a shared code history without merging their private databases or granting one local agent unrestricted access to another person's machine.

## Organization workspaces

An Amosclaud organization is an authorization and ownership boundary. The intended progression is:

### Available foundation

- organization records;
- organization members;
- role-based administration;
- organization repository attachment.

### Next maturity stage

- invitation and acceptance flows;
- teams within organizations;
- team-to-repository permissions;
- project and operation-bucket ownership by organization;
- organization policy inheritance;
- audit events for membership, secrets, tasks, and deployments;
- service accounts and scoped organization API keys;
- organization-level usage limits and billing ownership.

### Shared execution stage

- organization-controlled worker pools and Server Stations;
- repository-scoped execution grants;
- centrally issued short-lived task credentials;
- shared task visibility with role-based log access;
- approved deployment environments;
- policy-controlled access to local or cloud model capacity.

Shared execution must not mean that every organization member receives raw infrastructure credentials. The control plane should issue bounded tasks to approved workers and return evidence, status, and artifacts through authenticated APIs.

## Future amosclaud.com portal

The cloud portal can become the connective layer between independent Amosclaud nodes. Planned portal responsibilities may include:

- global account and organization identity;
- organization invitations and team administration;
- centralized plans, billing, entitlements, and usage reporting;
- registered Amosclaud nodes and Server Stations;
- repository and deployment coordination;
- shared operation buckets, approvals, and audit history;
- enterprise policy distribution;
- optional hosted workspaces and managed model services.

The portal should distinguish clearly between three kinds of data:

1. **portal-owned data** — accounts, plans, organization membership, node registration, and coordination metadata;
2. **explicitly synchronized data** — selected task status, audit records, deployment results, or artifacts sent under a defined policy; and
3. **local-only data** — private files, secrets, databases, model weights, terminal history, and other content that the user has not authorized for upload.

## Node registration and coordination contract

A future local node connection should use a bounded registration model:

```text
amosclaud.com
     │
     ├── identity, organization, policy, and task authorization
     │
     ▼
registered Amosclaud node
     │
     ├── private Node.js control plane
     ├── local Redis queue
     ├── local repositories
     ├── local or private models
     └── optional isolated workspace runtime
```

Recommended security properties:

- nodes initiate outbound authenticated connections where possible;
- credentials are installation-specific and revocable;
- task grants are short-lived and scoped to one organization, repository, operation, and capability;
- portal requests cannot bypass the local command allowlist or workspace policy;
- node owners can disable remote execution while keeping status synchronization enabled;
- every remote operation creates an auditable local record;
- success is reported only with runtime evidence.

## Deployment profiles

### Personal local node

One user controls one installation. GitHub provides optional remote source control. No central portal is required for basic operation.

### Organization-owned private node

An organization operates Amosclaud on its own server or network. Organization administrators govern members, repositories, workers, policies, and credentials.

### Hybrid portal-connected node

The installation keeps execution and private data locally while amosclaud.com coordinates identity, billing, organization policy, tasks, and deployments.

### Fully managed cloud workspace

Amosclaud operates the control plane, isolated workspace runtime, storage, and model integrations as a hosted service. This profile requires the strongest tenant isolation, ownership checks, secret management, auditing, quotas, and billing controls.

## Current recommendation for collaborators

Until shared cloud workspaces and cross-node coordination are production-ready, collaborators should:

- clone the repository into separate local Amosclaud installations;
- use GitHub branches and pull requests for code collaboration;
- keep secrets outside Git;
- maintain separate local databases and Redis instances;
- grant production and deployment permissions independently;
- use protected branches and required verification before merging agent-generated changes.

This approach lets other developers build alongside the project today while preserving the local-first privacy and independence that Amosclaud is intended to provide.
