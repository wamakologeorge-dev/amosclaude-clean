FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOME=/home/developer

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       build-essential \
       ca-certificates \
       curl \
       git \
       jq \
       nodejs \
       npm \
       openssh-client \
       python3 \
       python3-pip \
       python3-venv \
    && if getent passwd 1000 >/dev/null; then \
         existing_user="$(getent passwd 1000 | cut -d: -f1)"; \
         existing_group="$(getent group 1000 | cut -d: -f1)"; \
         if [ "$existing_group" != "developer" ]; then \
           groupmod --new-name developer "$existing_group"; \
         fi; \
         if [ "$existing_user" != "developer" ]; then \
           usermod --login developer \
             --home /home/developer \
             --move-home \
             --shell /bin/bash \
             "$existing_user"; \
         fi; \
       else \
         groupadd --gid 1000 developer; \
         useradd --uid 1000 --gid 1000 \
           --create-home --shell /bin/bash developer; \
       fi \
    && mkdir -p /workspace /home/developer/.cache \
    && chown -R developer:developer /workspace /home/developer \
    && rm -rf /var/lib/apt/lists/*

COPY services/workspace_runtime/workspace-image/entrypoint.sh /usr/local/bin/amosclaud-workspace-entrypoint
RUN chmod 0755 /usr/local/bin/amosclaud-workspace-entrypoint

USER developer
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/amosclaud-workspace-entrypoint"]
CMD ["sleep", "infinity"]
