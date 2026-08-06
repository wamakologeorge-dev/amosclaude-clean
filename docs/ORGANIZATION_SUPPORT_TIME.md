# Amosclaud organization support working time

Amosclaud official hosted tools use a prepaid working-time entitlement funded through verified organization support contributions.

## Payment methods

The currently supported external payment methods are:

- Cash App: `$kenjamakulu`
- Bitcoin through the official Cash App Bitcoin payment link

A payment-link visit, screenshot, customer-entered reference, or unverified claim is not proof of payment. An Amosclaud administrator must independently confirm the transaction before activation.

## Default support tiers

| Tier | Agent credits | Hosted working time |
| --- | ---: | ---: |
| Starter | 1,000 | 10 hours |
| Builder | 5,000 | 60 hours |
| Studio | 15,000 | 240 hours |

The time values can be configured with:

- `AMOSCLAUD_SUPPORT_STARTER_SECONDS`
- `AMOSCLAUD_SUPPORT_BUILDER_SECONDS`
- `AMOSCLAUD_SUPPORT_STUDIO_SECONDS`

Every successful hosted tool operation consumes at least `AMOSCLAUD_TOOL_SECONDS_PER_OPERATION`, which defaults to 60 seconds.

## Enforced hosted surfaces

The production combined gateway enforces working time for:

- Amosclaud API and OpenAI-compatible `/v1/*` routes
- Autonomous agents and model operations
- Repository, issue, pull-request, test, verification, and deployment actions
- Cloud workspaces, storage operations, and execution workers
- VS Code and browser-editor cloud actions
- Remote Amosclaud MCP tools

Authentication, account recovery, payment verification, support status, public documentation, and public source metadata remain reachable so a user can sign in and replenish access.

## Activation and expiration

1. The customer signs in to an Amosclaud account.
2. The customer selects a support tier and pays through Cash App or Bitcoin.
3. An administrator verifies the transaction independently.
4. `POST /api/v1/provider/payments/activate` records the verified payment reference.
5. Amosclaud adds the tier's credits and hosted working time atomically.
6. Duplicate payment references are rejected, including attempts to reuse the same reference under a different payment method.
7. When remaining working time reaches zero, customer tool requests return HTTP 402 with the organization-support page and payment methods.

The status endpoint is:

```text
GET /api/v1/support-time/status
```

The public support page is:

```text
/organization-support
```

## Open-source boundary

Public source code cannot be made technically impossible to modify or run locally while remaining genuinely open source. Amosclaud therefore enforces contributions at the official hosted control plane, official remote MCP endpoint, cloud workers, APIs, and managed editor integrations.

Official binaries may display support requirements, but anyone receiving open-source code can inspect or modify it under the repository license. Changing this would require a future source-available or commercial license and would not retroactively remove rights already granted for earlier open-source versions.

## Legal wording

Because hosted working time and credits are provided in exchange for payment, customer-facing text should describe the transaction as an **organization support contribution**, **service purchase**, or **prepaid hosted working time**. Do not represent it as a tax-deductible charitable donation unless the organization is legally qualified to issue charitable receipts in the relevant jurisdiction.
