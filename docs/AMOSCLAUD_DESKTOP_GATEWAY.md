# Amosclaud Desktop gateway setup

Amosclaud Desktop can use Amosclaud as a third-party model gateway through the
OpenAI-compatible `/v1` API. The Desktop app does not send a user key to the
web page and does not need an upstream OpenAI or Ollama secret: those provider
credentials remain server-side in Amosclaud.

## One-time setup

1. Open **Amosclaud Desktop**.
2. Choose **Amosclaud → Gateway provider setup**, or start the app with
   `Amosclaud --configure`.
3. Enter the Amosclaud deployment URL. The hosted default is
   `https://www.amosclaud.com`.
4. Enter the default model, normally `amosclaud-agent`.
5. Paste a scoped Amosclaud API key and choose **Test connection**.
6. Choose **Save securely** after the model list is returned.

The key is encrypted with Electron `safeStorage` and stored in the operating
system credential store. The configuration file contains only encrypted key
material, the URL, and the model name. Leaving the key field blank while
updating settings preserves the existing saved key.

The setup window is opened explicitly rather than on every launch. This keeps
the administrator’s normal session-based Desktop flow free of an unnecessary
key prompt. End users should use their own scoped `amos_aut_`, `amos_live_`, or
`amos_test_` key and the server continues to enforce payment, credits, key
scopes, repository authorization, approvals, and verification.

## Environment-driven setup

For managed Desktop deployments or development, configure the process without
opening the setup window:

```env
AMOSCLAUD_URL=https://www.amosclaud.com
AMOSCLAUD_GATEWAY_URL=https://www.amosclaud.com
AMOSCLAUD_API_KEY=amos_aut_replace_me
AMOSCLAUD_MODEL=amosclaud-agent
```

Environment values are used for the current process and take precedence over
the saved Desktop provider configuration. Never commit a real key or put it in
an installer, screenshot, issue, or shared project file.

## Third-party client settings

Any client that supports an OpenAI-compatible provider can use:

```text
Base URL: https://www.amosclaud.com/v1
Model:    amosclaud-agent
API key:  your scoped Amosclaud API key
```

The supported endpoints are:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`

Streaming is currently rejected explicitly. The credential-free discovery
document is available at
`https://www.amosclaud.com/.well-known/amosclaud-provider.json` and the same
metadata is available at `/api/v1/desktop/provider`.

## Desktop bridge API

The Desktop preload exposes a narrow provider bridge for the Amosclaud web
surface:

```javascript
const provider = window.amosclaudDesktop.provider;

const models = await provider.request({ path: '/v1/models' });
const response = await provider.request({
  path: '/v1/responses',
  method: 'POST',
  body: {
    model: 'amosclaud-agent',
    input: 'Explain the first verified blocker in this repository.',
  },
});
```

Only `/v1/models`, `/v1/chat/completions`, and `/v1/responses` are permitted.
The bridge adds the stored bearer credential in the main process, so the
renderer receives the response but never receives the raw API key. The bridge
also enforces HTTPS for remote gateways, allows HTTP only for exact loopback
development hosts, applies a 12-second request timeout, and caps response size.
