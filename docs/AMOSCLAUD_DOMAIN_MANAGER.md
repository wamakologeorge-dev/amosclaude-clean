# Amosclaud Domain Manager

Amosclaud Domain Manager independently verifies whether a public domain is actually connected to the expected Vercel project and serving through the Vercel edge.

## Verification chain

```text
Amosclaud Domain Manager
        ↓
Vercel API
        ↓
Check domain exists on project
        ↓
Check domain access verification
        ↓
Check DNS configuration
        ↓
Check HTTPS/public response
        ↓
Check Vercel edge evidence
        ↓
Amosclaud verification record
```

The manager does not mark a domain verified merely because it appears in a provider dashboard. Every required signal must pass.

## Truth states

- `verified` — project attachment, Vercel access verification, DNS configuration, HTTPS response, and Vercel edge evidence all pass.
- `blocked` — the domain is missing from the expected project or Vercel access verification is not satisfied.
- `misconfigured` — DNS is missing/misconfigured or the public response does not prove traffic reached Vercel.
- `unreachable` — provider/DNS checks pass but the public HTTPS endpoint cannot be used successfully.

A verification record preserves the individual evidence instead of reducing the result to a single green/red flag.

## API

The Domain Manager routes are mounted through the authenticated Amosclaud API surface.

```text
POST /api/v1/domains/verify
GET  /api/v1/domains/{domain}/verification
GET  /api/v1/domains/verification/history
```

Example request:

```json
{
  "domain": "amosclauds.com",
  "project": "amosclaud",
  "team_id": null
}
```

Example verified result shape:

```json
{
  "record_id": 42,
  "truth": {
    "domain": "amosclauds.com",
    "provider_expected": "vercel",
    "project": "amosclaud",
    "status": "verified",
    "verified": true,
    "project_domain": {"ok": true},
    "access_verification": {"ok": true},
    "dns_configuration": {"ok": true},
    "https_response": {"ok": true},
    "provider_edge": {"ok": true},
    "reasons": []
  }
}
```

## Configuration

The server reads these environment variables:

```text
VERCEL_TOKEN=<Vercel API token>
VERCEL_PROJECT_ID=<preferred project id>
VERCEL_PROJECT_NAME=<fallback project name>
VERCEL_TEAM_ID=<optional Vercel team id>
```

`VERCEL_TOKEN` is sent only to the Vercel API. It is not stored in the domain verification record or returned from the Amosclaud API.

## DNS and HTTPS proof

Amosclaud resolves public `A`, `AAAA`, `CNAME`, `TXT`, and `NS` records. HTTPS verification is refused when the resolved address is non-public, reducing the risk of the domain checker being used to probe private services.

The public response is considered Vercel edge evidence when Vercel-specific response evidence is present, such as `x-vercel-id`, or the server header identifies Vercel. A normal HTTP response without provider evidence is not enough for a `verified` result.

## Current implementation status

🟡 **Implemented / verification pending.** The Domain Manager engine, authenticated API routes, persistence record, and unit tests exist on the feature branch. This is not yet a claim that the feature is merged, deployed, or that `amosclauds.com` currently passes the verification chain. Those states require separate CI, merge, deployment, Vercel credentials, DNS configuration, and live verification evidence.
