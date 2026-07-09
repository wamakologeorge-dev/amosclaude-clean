# Amosclaud AI Platform

Self-hosted CI/CD and deployment automation for Amosclaud. The app includes a FastAPI server, web dashboard, pipeline/deployment APIs, and Amosclaud Copilot delegation endpoints.

## Quick Start

### Run With Docker

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean
cd amosclaude-clean
docker-compose up --build
```

- Dashboard: `http://localhost`
- API Docs: `http://localhost:8000/docs`

### Run With Python

```bash
pip install -r requirements.txt
python -m amoscloud_ai.main
```

- Dashboard: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

## What You Can Do

- Manage CI/CD pipelines.
- Trigger and rollback deployments.
- Monitor server health in real time.
- Delegate Amosclaud-owned work through Amosclaud Copilot.
- View the live dashboard at `/`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web dashboard |
| `GET` | `/health` | Server health check |
| `GET` | `/api/v1/copilot` | Amosclaud Copilot profile |
| `POST` | `/api/v1/copilot/delegate` | Delegate work to Amosclaud Copilot |
| `GET` | `/api/v1/pipelines` | List all pipelines |
| `POST` | `/api/v1/pipelines` | Create/trigger a pipeline |
| `GET` | `/api/v1/deployments` | List all deployments |
| `POST` | `/api/v1/deployments` | Start a deployment |
| `GET` | `/docs` | Interactive API docs |

## Amosclaud Copilot

Amosclaud Copilot is scoped to Amosclaud-owned application work. Its job is to delegate, build, monitor, and report back only for `amosclaud.com` and the Amosclaud pipeline.

## Production Deployment

The production stack for `amosclaud.com` is defined in `docker-compose.prod.yml`:

- FastAPI API server
- Celery worker
- PostgreSQL
- Redis
- Caddy reverse proxy with automatic HTTPS for `amosclaud.com` and `www.amosclaud.com`

On the production host, create `.env.production` from `.env.production.example`, point DNS for `amosclaud.com` and `www.amosclaud.com` at the host, then run:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

GitHub Actions deployment is available in `.github/workflows/deploy-amosclaud.yml`. Configure these repository secrets before running it:

- `AMOSCLAUD_SSH_HOST`
- `AMOSCLAUD_SSH_USER`
- `AMOSCLAUD_SSH_KEY`
- `AMOSCLAUD_APP_DIR`

Railway deployment metadata is included in `railway.json` and `Procfile`. If `amosclaud.com` is connected to Railway, merge or deploy this branch there, set production environment variables, and Railway will start `python -m amoscloud_ai.main` with `/health` as the health check.

## Project Structure

```text
amosclaude-clean/
├── amoscloud_ai/          # Main FastAPI application package
│   ├── api/routes/        # health, copilot, pipelines, deployments routes
│   ├── main.py            # App entry point; serves API and web dashboard
│   ├── config.py          # Settings
│   └── models.py          # Pydantic models
├── web/                   # Frontend dashboard served at /
├── tests/                 # pytest test suite
├── Dockerfile             # App container
├── docker-compose.yml     # Local stack
├── docker-compose.prod.yml # Production stack
├── Caddyfile              # Production HTTPS reverse proxy
└── nginx.conf             # Local reverse proxy config
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./amoscloud.db` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `SECRET_KEY` | `change-me-in-production` | App secret key; change in production |
| `ENVIRONMENT` | `development` | Runtime environment |
| `LOG_LEVEL` | `INFO` | Logging level |
