FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOME=/home/developer

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       bash-completion \
       build-essential \
       ca-certificates \
       cmake \
       curl \
       dnsutils \
       fd-find \
       file \
       gdb \
       git \
       git-lfs \
       iproute2 \
       jq \
       less \
       lsof \
       nano \
       ncurses-term \
       net-tools \
       netcat-openbsd \
       nodejs \
       npm \
       openssh-client \
       pkg-config \
       procps \
       python3 \
       python3-dev \
       python3-pip \
       python3-venv \
       ripgrep \
       rsync \
       shellcheck \
       sqlite3 \
       strace \
       tmux \
       tree \
       unzip \
       vim-tiny \
       wget \
       zip \
    && git lfs install --system \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
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
COPY services/workspace_runtime/workspace-image/terminal-profile.sh /etc/profile.d/amosclaud-terminal.sh
COPY services/workspace_runtime/workspace-image/amos /usr/local/bin/amos
RUN chmod 0755 \
      /usr/local/bin/amosclaud-workspace-entrypoint \
      /etc/profile.d/amosclaud-terminal.sh \
      /usr/local/bin/amos

USER developer
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/amosclaud-workspace-entrypoint"]
CMD ["sleep", "infinity"]
