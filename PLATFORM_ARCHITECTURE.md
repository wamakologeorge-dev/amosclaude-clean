# Amosclaud Service Ecosystem

| Boundary | Canonical location | Responsibility |
|---|---|---|
| Agent framework | `packages/agent-core` | Native planning, tools, state, evidence, verification |
| Developer gateway | `services/gateway` | API authentication, ownership, rate controls, routing |
| Agent definitions | `agents` | Capabilities, targets, and guardrail manifests |
| SDKs | `packages/sdk-*` | Stable client interfaces for external applications |
| Host tools | `tools` and console commands | Workspace, memory, runner, and language utilities |
| API contract | `openapi.yaml` | Machine-readable developer and agent interface |
| Deployment | Docker and server release workflows | Cloud and self-hosted runtime packaging |

Customer calls enter through `/api/v1`, authenticate with an Amosclaud-issued key, reserve prepaid credits, and receive one owned task ID. The router selects cloud, self-hosted, or connected GitHub execution. Every terminal result records evidence and artifacts. Provider credentials remain inside the service boundary.

The authoritative live FastAPI schema remains `/openapi.json`; `openapi.yaml` is the deliberately small public integration contract. CI validates both the application and public contract on every pull request.
