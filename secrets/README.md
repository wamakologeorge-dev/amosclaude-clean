# Production Docker secrets

Do not commit real secret values. Every file in this directory except this
README is ignored by Git.

Create the required files on the production host with restrictive permissions:

```bash
umask 077
mkdir -p secrets

openssl rand -hex 32 > secrets/postgres_password
openssl rand -hex 32 > secrets/redis_password
openssl rand -hex 48 > secrets/secret_key
openssl rand -hex 48 > secrets/amosclaud_master_key
openssl rand -hex 32 > secrets/metrics_token
openssl rand -base64 32 | tr -d '\n' > secrets/github_token_encryption_key
```

Create independent values for enabled optional services:

```bash
openssl rand -base64 32 | tr -d '\n' > secrets/dashboard_key
openssl rand -hex 32 > secrets/byte_bus_secret
openssl rand -hex 32 > secrets/preview_service_key
openssl rand -hex 32 > secrets/amosclaud_api_key
printf '%s' 'replace-with-github-oauth-client-secret' > secrets/github_client_secret
printf '%s' 'replace-with-model-service-token' > secrets/model_token
printf '%s' 'replace-with-stripe-secret-key' > secrets/stripe_secret_key
printf '%s' 'replace-with-stripe-webhook-secret' > secrets/stripe_webhook_secret
```

When an optional integration is disabled, its file must still exist because the
Compose file declares it as a mounted secret. Create an empty file instead of a
fake credential:

```bash
touch \
  secrets/dashboard_key \
  secrets/byte_bus_secret \
  secrets/preview_service_key \
  secrets/amosclaud_api_key \
  secrets/github_client_secret \
  secrets/model_token \
  secrets/stripe_secret_key \
  secrets/stripe_webhook_secret
chmod 600 secrets/*
```

The application startup script rejects empty values for the six required base
secrets: PostgreSQL password, Redis password, application `SECRET_KEY`,
`AMOSCLAUD_MASTER_KEY`, metrics token, and GitHub token-encryption key.

Rotate one secret at a time. After replacing a file, recreate the affected
containers so Docker remounts the new value:

```bash
docker compose --env-file .env.production up -d --force-recreate postgres redis amoscloud_api
```

Changing encryption keys can make previously encrypted records unreadable.
Back up the database and persistent `/data` volume before rotating
`AMOSCLAUD_MASTER_KEY`, `GITHUB_TOKEN_ENCRYPTION_KEY`, or dashboard encryption
keys.
