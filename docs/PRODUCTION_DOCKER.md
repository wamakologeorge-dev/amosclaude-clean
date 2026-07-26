# Amosclaud production Docker deployment

This stack runs the Amosclaud API behind an HTTPS reverse proxy with persistent
PostgreSQL, authenticated Redis, Docker-mounted secret files, and automatic
Let's Encrypt certificate management through Caddy.

## Architecture

- **Caddy** is the only public service. It binds TCP 80/443 and UDP 443,
  redirects the apex domain to the primary domain, obtains and renews TLS
  certificates, adds security headers, and proxies requests to the API.
- **Amosclaud API** is exposed only to Docker networks. It is not published on a
  host port.
- **PostgreSQL** and **Redis** are attached only to the internal backend network.
- **Docker secrets** are mounted read-only under `/run/secrets`; the production
  entrypoint exports them only inside the application process.
- Application repositories, authentication data, Caddy certificates,
  PostgreSQL data, and Redis append-only data use named persistent volumes.

## Host prerequisites

1. Install Docker Engine with the Docker Compose v2 plugin.
2. Point DNS records for `amosclaud.com` and `www.amosclaud.com` to the host.
3. Allow inbound TCP 80 and 443 and UDP 443 through the host and cloud firewall.
4. Ensure the model endpoint configured by `AMOSCLAUD_MODEL_URL` is reachable
   from the API container.
5. Back up the host and named volumes before replacing an existing deployment.

Caddy cannot issue a public certificate until DNS points to the host and TCP
port 80 or 443 is reachable from the internet.

## Prepare configuration

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Edit `.env.production` and set the domains, ACME email, GitHub OAuth client ID,
model endpoint, and any enabled Stripe price identifiers. This file contains
non-secret deployment settings only.

Generate secret files by following [`secrets/README.md`](../secrets/README.md).
Do not paste real secrets into `docker-compose.yml`, `.env.production`, the
Caddyfile, shell history, or GitHub.

## Validate before starting

```bash
docker compose --env-file .env.production config >/tmp/amosclaud-compose.yml
docker compose --env-file .env.production build amoscloud_api
docker run --rm \
  -e PRIMARY_DOMAIN=www.amosclaud.com \
  -e APEX_DOMAIN=amosclaud.com \
  -e ACME_EMAIL=ops@example.com \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```

The rendered Compose output must not display secret values. It should show only
secret file references under the top-level `secrets` section.

## Start and inspect

```bash
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 caddy amoscloud_api
```

Verify:

```bash
curl -I https://www.amosclaud.com/health
curl -I https://amosclaud.com/
```

Expected behavior:

- the apex domain redirects permanently to the primary domain;
- the primary domain presents a valid public certificate;
- `/health` reaches the API through Caddy;
- ports 5432, 6379, and 8000 are not published on the Docker host.

## Updating

```bash
git pull --ff-only
docker compose --env-file .env.production build --pull amoscloud_api
docker compose --env-file .env.production up -d --remove-orphans
docker image prune -f
```

Caddy renews certificates automatically. Keep the `caddy_data` volume; deleting
it removes certificate state and can trigger certificate-authority rate limits.

## Backups

Create application-data and PostgreSQL backups before upgrades or secret
rotation:

```bash
mkdir -p backups

docker compose --env-file .env.production exec -T postgres \
  pg_dump -U "$(grep '^POSTGRES_USER=' .env.production | cut -d= -f2-)" \
  "$(grep '^POSTGRES_DB=' .env.production | cut -d= -f2-)" \
  > "backups/postgres-$(date +%Y%m%d-%H%M%S).sql"

docker run --rm \
  -v amosclaud_amoscloud_data:/source:ro \
  -v "$PWD/backups:/backup" \
  alpine sh -c 'tar czf /backup/amoscloud-data-$(date +%Y%m%d-%H%M%S).tgz -C /source .'
```

The exact volume prefix is controlled by `COMPOSE_PROJECT_NAME`. Confirm names
with `docker volume ls` before running backup or restore commands.

## Recovery and troubleshooting

- **Caddy cannot obtain a certificate:** verify public DNS, firewall rules,
  correct domain variables, and that no other process owns ports 80 or 443.
- **API remains unhealthy:** inspect `docker compose logs amoscloud_api`; startup
  fails deliberately when a required secret file is missing or empty.
- **Database or Redis is unhealthy:** verify the matching secret file exists,
  contains no trailing accidental spaces, and is readable by Docker.
- **Model runtime is unreachable:** test the configured URL from inside the API
  container and confirm the inference service listens on the expected host and
  port.
- **OAuth callback mismatch:** configure the GitHub OAuth application with
  `https://<PRIMARY_DOMAIN>/api/v1/auth/github/callback` and the repository app
  callback with `https://<PRIMARY_DOMAIN>/api/v1/github/callback`.
