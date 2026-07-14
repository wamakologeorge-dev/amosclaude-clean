#!/usr/bin/env bash
set -Eeuo pipefail
install_root="$(cd "$(dirname "$0")" && pwd)"
app_root="$install_root"
[[ -f "$install_root/app/docker-compose.selfhost.yml" ]] && app_root="$install_root/app"
cd "$app_root"

command -v docker >/dev/null || { echo "Docker is required. Install and start Docker, then retry." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "The Docker engine is not running." >&2; exit 1; }
mkdir -p "$install_root/AmosclaudWorkspace"
touch .env.runner
chmod 600 .env.runner

if [[ ! -f .env ]]; then
  read -r -p "Owner email: " owner
  [[ -n "$owner" ]] || { echo "Owner email is required." >&2; exit 1; }
  key="$(python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(48)).decode())')"
  umask 077
  printf '%s\n' "AMOSCLAUD_MASTER_KEY=$key" "AMOSCLAUD_ADMIN_EMAIL=$owner" \
    "AMOSCLAUD_ACCESS_MODE=local" "AMOSCLAUD_MODEL=qwen2.5-coder:3b" > .env
fi
grep -q '^AMOSCLAUD_WORKSPACE_PATH=' .env || printf '%s\n' \
  "AMOSCLAUD_WORKSPACE_PATH=$install_root/AmosclaudWorkspace" >> .env

profile=()
read -r -p "Connect this computer to amosclaud.com as a private runner? (y/N) " connect
if [[ "$connect" =~ ^[Yy]$ ]]; then
  read -r -p "Runner ID from amosclaud.com/tasks: " runner_id
  read -r -s -p "One-time runner token: " runner_token; echo
  [[ -n "$runner_id" && -n "$runner_token" ]] || { echo "Runner ID and token are required." >&2; exit 1; }
  umask 077
  printf '%s\n' "AMOSCLAUD_API_URL=https://amosclaud.com" "AMOSCLAUD_RUNNER_ID=$runner_id" \
    "AMOSCLAUD_RUNNER_TOKEN=$runner_token" > .env.runner
  grep -q '^AMOSCLAUD_RUNNER_WORKSPACE=' .env || printf '%s\n' \
    "AMOSCLAUD_RUNNER_WORKSPACE=$install_root/AmosclaudWorkspace" >> .env
  profile=(--profile connected-runner)
fi

docker compose -f docker-compose.selfhost.yml "${profile[@]}" up -d --build
echo "Amosclaud is installed as restartable Docker services."
echo "Open http://localhost:8000 after the health check becomes ready."
