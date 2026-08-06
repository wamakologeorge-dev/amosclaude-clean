# Amosclaud API payment activation

Amosclaud's open-source developer tools remain available without payment. Hosted Amosclaud API access is a paid service.

## Customer flow

1. Sign in to the Amosclaud account that will own the API key.
2. Open `/api-access`.
3. Select Starter, Builder, or Studio.
4. Pay through the official Cash App or Bitcoin link shown on that page.
5. Include the pack name and the Amosclaud account email or GitHub username in the payment note.
6. Wait for Amosclaud to verify the payment.
7. Create the installation API key only after the account reports `api_activated: true`.

A payment-link visit, screenshot, or user-supplied reference is not proof of settlement. Amosclaud must verify the payment independently before activation.

## Activation contract

Unauthenticated users cannot manage keys. Signed-in non-administrator users cannot create or use an API key until a verified payment has been recorded with one of these ledger reasons:

- `cash_app_payment`
- `bitcoin_payment`

Previously created unpaid keys are also blocked. An activated key still requires a positive credit balance for requests. Requests that cannot reserve the required credits return HTTP 402.

The platform administrator may create an internal owner key without customer payment. This exception is limited to accounts whose `is_admin` field is true.

## Administrator verification

After independently verifying the external transaction, an authenticated administrator activates the customer account through:

```http
POST /api/v1/provider/payments/activate
Content-Type: application/json

{
  "user_email": "customer@example.com",
  "pack": "starter",
  "method": "cash_app",
  "payment_reference": "verified-provider-reference"
}
```

For Bitcoin, set `method` to `bitcoin`. The server adds the fixed credits for the selected pack and records the payment reference idempotently. Reusing a verified reference returns HTTP 409 and cannot add credits twice.

## Disabled checkout path

Public Stripe checkout endpoints return HTTP 410. The supported activation methods are Cash App and Bitcoin with manual verification.

Never store Cash App passwords, PINs, Bitcoin private keys, wallet recovery phrases, Amosclaud API keys, or account recovery codes in payment notes or verification records.
