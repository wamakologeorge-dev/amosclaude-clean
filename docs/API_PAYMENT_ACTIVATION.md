# Amosclaud API payment activation

Customer Amosclaud API access is activated through verified organization support paid by Cash App or Bitcoin.

## Customer flow

1. Create or sign in to an Amosclaud account.
2. Open `/organization-support` or `/api-access`.
3. Choose Starter, Builder, or Studio.
4. Pay through the official Cash App or Bitcoin link.
5. Include the tier and the Amosclaud account email or GitHub username in the payment note.
6. Wait for an Amosclaud administrator to independently verify the transaction.
7. After verification, the account receives agent credits and hosted working time.
8. The customer can create an Amosclaud API key while working time remains.

## Default entitlements

| Tier | Agent credits | Hosted working time |
| --- | ---: | ---: |
| Starter | 1,000 | 10 hours |
| Builder | 5,000 | 60 hours |
| Studio | 15,000 | 240 hours |

Higher organization support produces more working time. Values are configurable through the `AMOSCLAUD_SUPPORT_*_SECONDS` environment variables.

## Administrator verification

The authenticated platform administrator verifies the external transaction and calls:

```text
POST /api/v1/provider/payments/activate
```

Example body:

```json
{
  "user_email": "customer@example.com",
  "pack": "builder",
  "method": "bitcoin",
  "payment_reference": "verified-transaction-reference"
}
```

The activation is atomic:

- the fixed agent-credit package is added,
- the matching hosted working time is added,
- the payment reference is recorded,
- duplicate references are rejected even if someone changes the claimed payment method.

A payment screenshot, payment-link visit, or customer-entered reference is not sufficient evidence by itself.

## Runtime enforcement

Official hosted operations are protected by the production gateway. A customer with no remaining working time receives HTTP 402 before an official tool runs.

Enforced surfaces include:

- Amosclaud API and OpenAI-compatible `/v1/*` endpoints,
- hosted autonomous agents and model operations,
- repositories, issues, pull requests, verification, and deployment actions,
- cloud workspaces and workers,
- VS Code cloud actions,
- remote Amosclaud MCP tools.

Every successful hosted operation consumes at least `AMOSCLAUD_TOOL_SECONDS_PER_OPERATION`, which defaults to 60 seconds. The response includes `X-Amosclaud-Support-Seconds-Remaining` when applicable.

Account access, payment verification, support status, and public source/documentation routes remain available so a customer can sign in and replenish working time.

## Status

```text
GET /api/v1/support-time/status
```

## Terminology

Because credits and working time are provided in exchange for payment, public wording should use **organization support contribution**, **service purchase**, or **prepaid hosted working time**. Do not promise a tax deduction unless Amosclaud is legally qualified to issue charitable receipts.
