#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

CONFIG_PATH="${1:-./wg0-server.conf}"
if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "WireGuard server configuration not found: ${CONFIG_PATH}" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard-tools nftables

install -d -m 700 /etc/wireguard
install -m 600 "${CONFIG_PATH}" /etc/wireguard/wg0.conf

cat >/etc/sysctl.d/99-amoscloud-gateway.conf <<'EOF'
net.ipv4.ip_forward=1
EOF
sysctl --system

systemctl enable --now nftables
systemctl enable --now wg-quick@wg0

wg show wg0

echo "Amosclaud WireGuard gateway is active."
echo "Open the configured UDP listen port in the VPS provider firewall."
