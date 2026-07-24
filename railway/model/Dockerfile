FROM ollama/ollama:latest

ENV OLLAMA_HOST=0.0.0.0:11434 \
    AMOSCLAUD_MODEL=qwen2.5-coder:3b

COPY start-model.sh /usr/local/bin/start-model.sh
RUN chmod 0755 /usr/local/bin/start-model.sh

EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=10 \
  CMD ollama list >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/local/bin/start-model.sh"]
