# Gateway, GitHub, VS Code, and MCP Integration

Amosclaud uses one public deployment at `https://www.amosclaud.com`. The same
account, operation bucket, task ID, and verification evidence are shared by the
website, API clients, GitHub Actions, VS Code, and MCP tools.

## Existing production components

The canonical application already provides:

- per-user operation buckets at `GET /api/v1/operations/bucket`;
- governed operations at `POST /api/v1/tasks`;
- operation status and logs at `GET /api/v1/tasks/{task_id}` and
  `GET /api/v1/tasks/{task_id}/logs`;
- OpenAI-compatible models, chat completions, and responses at `/v1`;
- remote MCP at `https://www.amosclaud.com/mcp/`;
- the native VS Code extension and repository-scoped terminal;
- cloud, GitHub, and self-hosted execution targets.

Do not deploy a second public control plane for the GitHub bot or MCP server.
They are adapters to the same operation ledger.

## Railway variables

Set the public URL consistently:

```env
PLATFORM_BASE_URL=https://www.amosclaud.com
PUBLIC_APP_URL=https://www.amosclaud.com
API_BASE_URL=https://www.amosclaud.com
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com
AMOSCLAUD_API_URL=https://www.amosclaud.com
```

Configure the model endpoint, Autonomous authentication, and remote MCP:

```env
AMOSCLAUD_MODEL_URL=http://amosclaud-model.railway.internal:8000
AMOSCLAUD_AUTONOMOUS_KEY=<sealed-value>
AMOSCLAUD_MCP_ACCESS_KEY=<separate-sealed-value>
AMOSCLAUD_OPENAI_COMPAT_MODELS=amosclaud-agent,gpt-4.1-mini
```

Only `www.amosclaud.com` needs a public domain. Private Railway services should
communicate over `*.railway.internal` addresses.

## GitHub Actions operation sync

The `Amosclaud Agent Sync` workflow submits a governed task to
`POST /api/v1/tasks`. Add these repository settings:

- Actions secret `AMOSCLAUD_API_KEY`: a per-user Amosclaud provider or
  Autonomous API key.
- Actions variable `AMOSCLAUD_API_URL`: normally
  `https://www.amosclaud.com`.

Run the workflow manually and provide one bounded objective. By default, the
operation remains in `awaiting_approval`; approving it in Amosclaud queues the
real GitHub execution. The workflow uploads `amosclaud-operation.json`, which
contains the task ID, bucket ID, status, selected repository, and operation
metadata.

A trusted Amosclaud control service may also send a `repository_dispatch` event
of type `amosclaud-operation`. The caller supplies `objective`, `mode`,
`delivery`, `require_approval`, and a unique `request_id` in `client_payload`.

## Continue

Copy `config/continue/amosclaud.yaml.example` into the Continue configuration
location and register `AMOSCLAUD_API_KEY` in Continue secrets. The configuration
uses:

```text
https://www.amosclaud.com/v1
```

The gateway implements both:

- `POST /v1/chat/completions`
- `POST /v1/responses`

Both endpoints authenticate the Amosclaud key, enforce the allowed model list,
reserve agent credits, refund failed upstream calls, and never forward the
user's Amosclaud credential to an upstream model provider.

## VS Code and MCP

The checked-in `.vscode/mcp.json` connects VS Code to:

```text
https://www.amosclaud.com/mcp/
```

The remote MCP bearer credential is intentionally separate from normal browser
sessions. MCP tools call the same public Amosclaud task and pipeline APIs, so a
task started from VS Code remains visible in the user's operation bucket and on
the website.

## Shared operation identity

Every interface must preserve these values:

```json
{
  "id": "task_<operation-id>",
  "bucket_id": "bucket_<user-bucket>",
  "repository": "owner/repository",
  "status": "awaiting_approval",
  "execution_target": "github"
}
```

Never create an unrelated GitHub-only job identity. GitHub runs, pull requests,
test evidence, and verification IDs must be attached to the originating task.
