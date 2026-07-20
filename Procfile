# For a background worker agent pulling from a queue (Redis/Postgres)
worker: python worker.py

# For a multi-agent system with an orchestrator API
web: uvicorn orchestrator:app --host 0.0.0.0 --port $PORT
worker_researcher: python -m agents.researcher
worker_writer: python -m agents.writer
