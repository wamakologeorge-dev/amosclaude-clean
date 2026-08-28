# Railway engine-room manifest

Everything Railway knows that the repo must remember. **Names and structure only — secret values NEVER live here.**
Purpose: Amosclaud can leave Railway using this file + owner's secret backup. See `docs/ONE_AMOSCLAUD.md`.

## Services (project `adequate-fulfillment`, env `production`)
| Service | What | Source |
|---|---|---|
| `amosclaude-clean` | main API + web + embedded worker | this repo, branch `main`, `railway.json` (Dockerfile build; healthcheck `/health`) |
| `Redis` | queue/cache | Railway plugin |
| `amosclaud-model` | ollama model runtime (side experiment) | container |

## Attached storage
- Volume mounted at `/data` on `amosclaude-clean` — holds `auth.db` (`AUTH_DB_PATH=/data/auth.db`) and runtime state. **Backup before any migration.**

## Custom domains on `amosclaude-clean`
- `amosclauds.com` (primary), `www.amosclauds.com` — DNS at Vercel; TLS minted by Railway edge today.

## Environment variables (names + status; values in owner's secret store)
| Name | Status | Purpose |
|---|---|---|
| SECRET_KEY | SET | session/JWT signing |
| GITHUB_TOKEN_ENCRYPTION_KEY | SET | encrypts linked GitHub tokens |
| AUTH_SESSION_DAYS | SET (30) | session lifetime |
| AUTH_DB_PATH | SET (/data/auth.db) | auth database location |
| SMTP_FROM | SET | outbound mail sender |
| RESEND_API_KEY | SET (verify committed) | HTTPS mail lane (Railway blocks SMTP) |
| PYTHONPATH | SET (/app) | imports |
| GITHUB_TOKEN (+3 variants) | SET — ROTATE | bot/API access |
| ANTHROPIC keys ×2 | SET — ROTATE | optional adapter |
| SMTP_PASSWORD | SET — ROTATE (owner's real Gmail pw!) | legacy SMTP lane |
| AMOSCLAUD_OLLAMA_API_KEY | PENDING | model gateway |
| GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET | PENDING | Google sign-in |
| AMOSCLAUD_WORKSPACE_RUNTIME_URL / _TOKEN | PENDING | SpaceCodeMe backend |

## Known dead weight
- `Procfile` points at `orchestrator:app` — stale; Railway uses `railway.json`. Remove or align.

## Exit checklist (short form)
1. Backup `/data` volume + export env values (owner secret store).
2. New host: `docker-compose.selfhost.yml` up; restore `/data`; set env.
3. Verify: `/health`, login, webhook delivery, mail send.
4. DNS flip via Domain Manager (TTL 300). 72h fallback window.
5. Decommission + rotate everything Railway held.
