# Amosclaud Full Package billing

Amosclaud supports a free Community plan and a paid Full Package. The paid entitlement can come from Stripe Billing or a manually issued license key.

## Stripe setup

Create one recurring monthly Price and one recurring annual Price in Stripe. Configure:

```env
AMOSCLAUD_PUBLIC_URL=https://www.amosclaud.com
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_FULL_MONTHLY_PRICE_ID=price_...
STRIPE_FULL_ANNUAL_PRICE_ID=price_...
```

Register this webhook endpoint:

```text
https://www.amosclaud.com/api/v1/billing/webhook
```

Subscribe it to:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `checkout.session.async_payment_failed`
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
- Do not grant access from the checkout redirect alone; wait for a verified webhook or retrieve the paid Checkout Session from Stripe server-side.

## Amosclaud API keys and agent credits

Customer installations use `AMOSCLAUD_API_KEY`; they never receive Amosclaud's private upstream model credentials. A signed-in customer creates a key at `/api-access`. Only the key hash is stored.

### Credit pack pricing

For each credit pack, configure either a Stripe one-time Price ID or an inline amount in the smallest currency unit. Do not configure both unless the Price ID should take priority.

Using Stripe Price IDs:

```env
STRIPE_AGENT_STARTER_PRICE_ID=price_...
STRIPE_AGENT_BUILDER_PRICE_ID=price_...
STRIPE_AGENT_STUDIO_PRICE_ID=price_...
```

Or using server-controlled inline USD amounts:

```env
STRIPE_AGENT_CURRENCY=usd
STRIPE_AGENT_STARTER_AMOUNT_CENTS=1000
STRIPE_AGENT_BUILDER_AMOUNT_CENTS=4000
STRIPE_AGENT_STUDIO_AMOUNT_CENTS=10000
```

The example amounts above are configuration examples only. Set the actual Amosclaud prices before production deployment.

The credit quantities are fixed by the application:

- Starter: 1,000 credits
- Builder: 5,000 credits
- Studio: 15,000 credits

Set the per-request debit separately:

```env
AMOSCLAUD_AGENT_CREDITS_PER_REQUEST=1
```

### Cards, debit cards, and bank accounts

Amosclaud redirects customers to Stripe-hosted Checkout. Card and debit-card collection is handled by Stripe. To offer US bank-account payments, enable ACH Direct Debit in the Stripe Dashboard payment-method settings. The application intentionally does not hard-code `payment_method_types`, allowing Stripe's dynamic payment methods to display eligible methods for the account, currency, amount, and customer.

Bank payments can settle after Checkout returns. The webhook must therefore include `checkout.session.async_payment_succeeded` and `checkout.session.async_payment_failed`. Amosclaud credits the wallet only after Stripe reports `payment_status=paid`.

### Settlement and idempotency

A verified paid Checkout Session credits the wallet exactly once using the Checkout Session ID as the ledger reference. This prevents duplicate credits when both `checkout.session.completed` and `checkout.session.async_payment_succeeded` are delivered or when Stripe retries a webhook.

The successful redirect returns to:

```text
https://www.amosclaud.com/api-access?checkout=success&session_id={CHECKOUT_SESSION_ID}
```

The page retrieves the Checkout Session from Stripe through the authenticated Amosclaud backend and refreshes the balance. This is a recovery path for delayed webhooks; it does not trust URL query parameters as proof of payment.

Each successful agent request debits the configured credit amount. Runtime failures refund the debit.

The downloadable package uses:

```env
AMOSCLAUD_API_URL=https://www.amosclaud.com
AMOSCLAUD_API_KEY=amos_live_customer_key
```

Owner OpenAI, Anthropic, Ollama, or other upstream model credentials must remain only on Amosclaud-controlled provider infrastructure.
