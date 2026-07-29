# Amosclaud Registry

Status: **first-party discovery and trust metadata service**

The Amosclaud Registry catalogs capabilities, editor clients, services, skills, and adapters that can participate in the Amosclaud ecosystem. The Registry is metadata-only: it never imports, installs, or executes code from an entry.

## Identity boundary

The Registry does not introduce separate user-facing agents. The public identity remains:

```json
{
  "name": "Amosclaud Autonomous",
  "type": "one-agent"
}
```

Capability entries such as Codex, Fixer, Action, Security, Clean, Autonomous, and AI describe internal routing roles available through the existing `/api/v1/copilot` adapter. They cannot bypass the canonical Autonomous kernel, branch controls, approval gates, verification, or Results reporting.

## Entry kinds

- `capability` — bounded internal work type or routing role;
- `client` — VS Code, Xcode, CLI, or another approved user interface;
- `service` — a platform service such as Copilot API or the Node control plane;
- `skill` — a discoverable `SKILL.md` package or bounded skill manifest;
- `adapter` — a reviewed compatibility or provider adapter.

## Trust and status

Trust levels:

- `first-party` — immutable entries seeded from the canonical repository;
- `approved` — administrator-reviewed custom metadata;
- `community` — administrator-registered community metadata.

Statuses:

- `active`;
- `experimental`;
- `deprecated`;
- `disabled`.

Disabled entries remain in the database for auditability but are hidden from public discovery.

## Persistence

The Registry uses the canonical Amosclaud SQLite database and creates the table:

```text
amosclaud_registry_entries
```

Each record stores normalized JSON arrays for capabilities and platforms, bounded metadata, creation/update timestamps, trust and status, and a deterministic SHA-256 metadata digest.

The digest covers Registry metadata only. It is not a package signature, executable attestation, malware scan, or proof that a remote artifact is safe.

## First-party manifest

The built-in manifest includes:

- Autonomous, Codex, Fixer, Action, Security, Clean, and AI capability roles;
- portable `amosclaud-ide` CLI;
- VS Code companion;
- Xcode companion;
- Copilot routing API;
- Node.js asynchronous control plane.

Built-in entries are immutable and are restored from repository code when the Registry initializes.

## Public API

### Summary

```http
GET /api/v1/registry
```

Returns schema version, one-agent identity, counts, available capabilities, platforms, and endpoint links.

### Discover entries

```http
GET /api/v1/registry/entries
GET /api/v1/registry/entries?kind=client
GET /api/v1/registry/entries?capability=chat
GET /api/v1/registry/entries?platform=xcode
GET /api/v1/registry/entries?status=experimental
```

### Get one entry

```http
GET /api/v1/registry/entries/client.vscode
```

### Capability providers

```http
GET /api/v1/registry/capabilities
```

### Immutable first-party manifest

```http
GET /api/v1/registry/manifest
```

## Administrator API

Mutations require a signed-in Amosclaud administrator session and are written to the administrator audit log.

### Register metadata

```http
POST /api/v1/registry/entries
Content-Type: application/json
Cookie: amos_session=...
```

```json
{
  "id": "skill.example-review",
  "kind": "skill",
  "title": "Example review skill",
  "description": "Provides bounded repository review metadata.",
  "version": "0.1.0",
  "status": "experimental",
  "trust": "community",
  "entrypoint": "skills/example-review/SKILL.md",
  "source_url": "https://github.com/example/example-review",
  "capabilities": ["review", "explanation"],
  "platforms": ["cli", "vscode"],
  "metadata": {"license": "example"}
}
```

### Update mutable metadata

```http
PATCH /api/v1/registry/entries/skill.example-review
```

### Disable mutable metadata

```http
DELETE /api/v1/registry/entries/skill.example-review
```

Delete is deliberately a soft disable. First-party entries cannot be changed or disabled through the API.

## Validation boundaries

- entry IDs and capability/platform tokens use bounded lowercase identifiers;
- URL entrypoints and source URLs must use HTTPS;
- absolute entrypoints are limited to `/api/...` routes;
- relative entrypoints cannot contain `..` traversal;
- metadata is capped at 16,000 serialized characters;
- custom entries cannot claim `first-party` trust;
- registration does not install dependencies or execute commands.

## Extension path

Future work may add artifact signatures, package publication, compatibility ranges, revocation lists, and an administrator UI. Those features require separate security review and must distinguish metadata validation from executable artifact verification.
