# Amosclaud Full Package billing

Amosclaud supports a free Community plan and a paid Full Package. The paid entitlement can come from Stripe Billing or a manually issued license key.

## Stripe setup

Create one recurring monthly Price and one recurring annual Price in Stripe. Configure:

```env
AMOSCLAUD_PUBLIC_URL=https://your-domain.example
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_FULL_MONTHLY_PRICE_ID=price_...
STRIPE_FULL_ANNUAL_PRICE_ID=price_...
```

Register this webhook endpoint:

```text
https://your-domain.example/api/v1/billing/webhook
```

Subscribe it to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Use Stripe test-mode credentials and the Stripe CLI before enabling live mode.

## Manual licenses

An authenticated administrator can issue a license with `POST /api/v1/billing/licenses`. The plaintext key is returned once; only its SHA-256 hash is retained. A signed-in customer activates it with `POST /api/v1/billing/license/activate`.

## Entitlements

`GET /api/v1/billing/status` is the server-side source of truth. Paid features must call `require_full_package(user_id)`; hiding a button in the browser is not an access control.

## Security rules

- Never place Stripe secret keys or webhook secrets in browser code.
- Never commit live credentials or populated `.env` files.
- Verify every webhook signature from the raw request body.
- Do not grant access from the checkout redirect alone; wait for a verified webhook.


## Amosclaud API keys and agent credits

Customer installations use `AMOSCLAUD_API_KEY`; they never receive Amosclaud's private upstream model credentials. A signed-in customer creates a key at `/api-access`. Only the key hash is stored.

Prepaid credit packs are configured with:

```env
STRIPE_AGENT_STARTER_PRICE_ID=price_...
STRIPE_AGENT_BUILDER_PRICE_ID=price_...
STRIPE_AGENT_STUDIO_PRICE_ID=price_...
AMOSCLAUD_AGENT_CREDITS_PER_REQUEST=1
```

A verified `checkout.session.completed` event credits the wallet exactly once. Each successful agent request debits the configured credit amount. Runtime failures refund the debit.

The downloadable package uses:

```env
AMOSCLAUD_API_URL=https://amosclaud.com
AMOSCLAUD_API_KEY=amos_live_customer_key
```

Owner OpenAI, Anthropic, or self-hosted model credentials must remain only on Amosclaud-controlled provider infrastructure.
