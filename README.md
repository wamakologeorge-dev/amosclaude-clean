# 🚀 Amoscloud AI Platform

![Amoscloud AI Status](https://img.shields.io/badge/Amoscloud--AI-%F0%9F%9F%A2_Live_%26_Active-brightgreen)

Self-hosted CI/CD & Deployment Automation Platform. Runs entirely from GitHub — no external cloud needed.

## Quick Start

### Option 1: Run with Docker (Full Platform)

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean
cd amosclaude-clean
docker-compose up --build
```

- Dashboard: http://localhost — served by nginx on port 80
- API Docs: http://localhost:8000/docs

### Option 2: Run directly with Python

```bash
pip install -r requirements.txt
python -m amoscloud_ai.main
```

- Dashboard: http://localhost:8000
- API Docs: http://localhost:8000/docs

## What You Can Do

- 🔁 Manage CI/CD pipelines
- 🚀 Trigger and rollback deployments
- 💚 Monitor server health in real-time
- 📊 View live dashboard at `/`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web dashboard |
| `GET` | `/health` | Server health check |
| `GET` | `/api/v1/pipelines` | List all pipelines |
| `POST` | `/api/v1/pipelines` | Create/trigger a pipeline |
| `GET` | `/api/v1/deployments` | List all deployments |
| `POST` | `/api/v1/deployments` | Start a deployment |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

## Project Structure

```
amosclaude-clean/
├── amoscloud_ai/          # Main FastAPI application package
│   ├── api/routes/        # health, pipelines, deployments routes
│   ├── main.py            # App entry point — serves API + web dashboard
│   ├── config.py          # Settings (pydantic-settings)
│   └── models.py          # Pydantic models
├── web/                   # Frontend dashboard (served at /)
│   ├── index.html         # Dashboard UI
│   ├── style.css          # Dark theme CSS
│   └── app.js             # API fetch + auto-refresh
├── tests/                 # pytest test suite
├── Dockerfile             # Multi-stage build
├── docker-compose.yml     # Full stack: API + Redis + nginx
└── nginx.conf             # Reverse proxy config
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./amoscloud.db` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (optional) |
| `SECRET_KEY` | `change-me-in-production` | App secret key |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Logging level |
