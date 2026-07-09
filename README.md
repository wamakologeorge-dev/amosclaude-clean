# 🚀 Amosclaud AI - Professional CI/CD & Deployment Automation

**Amosclaud AI** is an intelligent, autonomous CI/CD automation system designed for developers. It acts first, reports later, and handles everything from integration testing to database management and intelligent deployment.

## ✨ Features

- ✅ **Amosclaud Copilot** - Higher-level delegation agent for amosclaud.com and the Amosclaud pipeline
- ✅ **Automated Integration Testing** - Run tests automatically on every commit
- ✅ **Smart Database Management** - Auto-migrate, backup, and optimize databases
- ✅ **Intelligent File Editing** - Analyze and modify code automatically
- ✅ **Code Deployment** - One-click deployment with rollback capabilities
- ✅ **Repository Management** - Clone, branch, commit operations
- ✅ **Real-time Reporting** - Comprehensive logs and status updates
- ✅ **Build Automation** - Compile and build projects automatically
- ✅ **Environment Management** - Auto-configure dev, staging, production

## Amosclaud Copilot

Amosclaud Copilot is scoped to Amosclaud-owned application work. Its job is to delegate, build, monitor, and report back only for amosclaud.com and the Amosclaud pipeline.

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

## 📋 Project Structure
