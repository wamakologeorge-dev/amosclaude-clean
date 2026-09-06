# Amosclaud Independent DNS Control Plane

Amosclaud now has a provider-neutral DNS desired-state control plane alongside the existing Vercel domain verifier.

## Architecture

```text
User / Amosclaud Agent
        |
        v
Amosclaud DNS Control API
        |
        v
Desired DNS Zone State
        |
        +----> Export / reconciliation adapter
        |
        v
Amosclaud DNS Judge
        |
        +---- zone validity
        +---- record validity
        +---- observed state matches desired state
        +---- duplicate detection
        |
        v
PASS / FAIL
```

The existing Vercel Domain Manager remains available as a provider-specific verifier. It is no longer the conceptual boundary for the new DNS management model.

## API

The independent control-plane endpoints are currently mounted under the authenticated domain surface:

```text
POST   /api/v1/domains/dns/zones
GET    /api/v1/domains/dns/zones
GET    /api/v1/domains/dns/zones/{domain}
POST   /api/v1/domains/dns/zones/{domain}/records
DELETE /api/v1/domains/dns/zones/{domain}/records
POST   /api/v1/domains/dns/zones/{domain}/judge
GET    /api/v1/domains/dns/zones/{domain}/export
```

## Amosclaud Action as judge

The native Amosclaud Action exposes DNS capabilities and treats `dns.judge` as the final deterministic health gate. A DNS operation should not be reported healthy merely because the desired state was written to the database.

The judge checks the desired zone and, when observed records are supplied, requires the observed set to contain the desired state. This is intentionally deterministic rather than model-generated.

## Current boundary

This milestone implements **DNS management/control-plane state**, validation, persistence, export, and the Action judging contract. It does **not** yet claim to be a public authoritative nameserver. The next infrastructure milestone is an authoritative DNS adapter/nameserver layer that publishes these zones on Amosclaud-controlled nameservers and feeds live observations back into `dns.judge`.

That separation is intentional: control-plane correctness can be tested before Amosclaud becomes the authoritative DNS provider for production domains.
