FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEMPLATE_STUDIO_DB=/data/template-studio.db

WORKDIR /app

COPY services/template_studio/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY services /app/services
RUN mkdir -p /data && useradd --create-home --uid 10001 template && chown -R template:template /data /app

USER template
EXPOSE 8090
CMD ["python", "-m", "services.template_studio"]
