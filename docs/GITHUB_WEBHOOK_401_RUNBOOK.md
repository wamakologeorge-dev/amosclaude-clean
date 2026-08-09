# GitHub webhook `401 Unauthorized` recovery

The Amosclaud GitHub App receiver is:

```text
https://www.amosclaud.com/api/v1/agent/github/webhook
```

A `401 Unauthorized` from this route means Amosclaud received the request but could not verify `X-Hub-Signature-256`. The receiver intentionally rejects unsigned or incorrectly signed events.

## Correct the configuration

1. Open the Amosclaud GitHub App settings and confirm the webhook URL is exactly the URL above.
2. Choose one strong random webhook secret. Do not reuse an API key, OAuth client secret, or GitHub token.
3. Set that exact value in Railway as `GITHUB_APP_WEBHOOK_SECRET` for the service serving `www.amosclaud.com`.
4. Set the same exact value in the GitHub App **Webhook secret** field.
5. Redeploy the Railway service, then use GitHub's webhook delivery page to redeliver a recent event.

A successful delivery returns HTTP `200`. Railway logs will identify a missing signature separately from a signature mismatch without printing the secret.

## Zero-downtime secret rotation

The application can temporarily accept two secrets:

```text
GITHUB_APP_WEBHOOK_SECRET=<new value>
GITHUB_APP_WEBHOOK_SECRET_PREVIOUS=<old value>
```

Deploy those variables first, update the GitHub App to the new value, verify a successful delivery, and then remove `GITHUB_APP_WEBHOOK_SECRET_PREVIOUS`. Leaving an old secret configured permanently increases risk.

## Do not bypass verification

Do not disable signature verification and do not send this endpoint a normal bearer token. GitHub App webhooks are authenticated only by the HMAC signature over the exact request body.
