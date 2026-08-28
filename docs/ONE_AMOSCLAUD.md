# One Amosclaud — Unification & Sovereignty Architecture

**Status:** Direction set by George (owner), 2026-08-28.
**Principle:** Amosclaud is ONE platform. Users see one console at `amosclauds.com` — Google Cloud / Codespaces style. External providers (Vercel, Railway, GitHub) are replaceable engine parts hidden behind Amosclaud's own control planes. See `docs/AMOSCLAUD_VISION.md` pillar 27.

## Layer map — who controls what

| Layer | Today | End state | Amosclaud control plane |
|---|---|---|---|
| Domain registration | Vercel (registrar) | Vercel stays (registrar ONLY) | Domain Manager (PR #1224) |
| DNS records | Vercel DNS → Railway edge | Amosclaud Domain Manager drives Vercel DNS API | `/api/v1/domains` |
| TLS | Railway edge certs | Amosclaud gateway (Caddy/Traefik) on own host | Domain Manager |
| Compute | Railway service `amosclaude-clean` | Amosclaud metal / VPS (self-host) | `deploy/` + SpaceCodeMe runners |
| Data | Railway `/data` volume + Redis | Amosclaud-managed volumes + backups | Storage controller (pillar 19) |
| Code hosting | GitHub | Amosclaud Repository Provider | Git gateway (pillar: Repository Provider) |
| CI | GitHub Actions | Amosclaud Actions + Runner Network | `.github/workflows` → `amosclaud actions` |
| Model | ollama (wamakologeorge/Amosclaud-clean) | Amosclaud first-party model | Model gateway |

**Rule:** every provider must be exitable using only what is in this repository plus a secrets backup. If leaving a provider would lose information, that information belongs in the repo (names/config — never secret values).

## The One Console

One shell, one auth, one header, product switcher (left nav):

```
amosclauds.com
├─ Console shell (one login, one nav)
│  ├─ Agent          (cloud/agent)
│  ├─ SpaceCodeMe    (workspaces: editor+terminal+runner)
│  ├─ Projects       (repos, PRs, issues, boards)
│  ├─ Applications   (deployed apps — pillar: Applications)
│  ├─ Domains        (Domain Manager — PR #1224)
│  ├─ Actions        (CI runs, runners)
│  ├─ Storage        (databases, buckets — pillar 19)
│  ├─ Monitoring     (logs, metrics, Doctor — pillars 21–22)
│  └─ Settings       (org, members, tokens, billing, policies)
```

Implementation order:
1. **Console shell PR** — unified nav/header mounted on existing pages; `/health` gains `build_sha` (claim→evidence).
2. **Domains live** — merge #1224, add Vercel DNS API credentials, manage DNS from Amosclaud.
3. **SpaceCodeMe MVP** — wire `workspace_worker/` container backend to the console.
4. Progressive: Storage, Monitoring, Actions views.

## Railway exit runbook (engine-room swap)

Railway already builds from this repo via `railway.json` (Dockerfile build, start command, healthcheck). What lives only in Railway's dashboard is inventoried in `deploy/railway.manifest.md`.

- **Phase 0 — inventory (done):** manifest in repo; secrets backed up by owner (never in repo).
- **Phase 1 — mirror:** stand up target host with `docker-compose.selfhost.yml`; restore `/data` backup; set env from manifest names; verify `/health`, login, GitHub webhooks.
- **Phase 2 — flip:** lower DNS TTL to 300; point records at new host via Domain Manager; verify; keep Railway hot for 72h as fallback.
- **Phase 3 — decommission:** delete Railway service; rotate any credentials Railway ever held.

**Evidence gates (pillar 20):** each phase passes only with proof — health JSON with matching `build_sha`, successful login session, webhook delivery log, TLS certificate issued.

## Non-goals right now
- No GitHub exit yet (Repository Provider comes later; GitHub remains the door, not the house).
- No big-bang rewrite: the console shell wraps existing pages first, then upgrades them in place.
