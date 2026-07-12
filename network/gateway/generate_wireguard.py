from __future__ import annotations

import argparse
import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatewayConfig:
    server_private_key: str
    server_public_key: str
    client_private_key: str
    client_public_key: str
    endpoint: str
    dns: str
    tunnel_network: ipaddress.IPv4Network
    wan_interface: str
    listen_port: int


def validate_key(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned.startswith("CHANGE_ME"):
        raise ValueError(f"{name} must contain a real WireGuard key")
    return cleaned


def render_server(config: GatewayConfig) -> str:
    server_ip = config.tunnel_network.network_address + 1
    client_ip = config.tunnel_network.network_address + 2
    return f"""[Interface]
Address = {server_ip}/{config.tunnel_network.prefixlen}
ListenPort = {config.listen_port}
PrivateKey = {validate_key('server private key', config.server_private_key)}
PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = nft add table ip amoscloud 2>/dev/null || true
PostUp = nft 'add chain ip amoscloud forward {{ type filter hook forward priority 0; policy drop; }}' 2>/dev/null || true
PostUp = nft 'add chain ip amoscloud postrouting {{ type nat hook postrouting priority 100; }}' 2>/dev/null || true
PostUp = nft add rule ip amoscloud forward iifname %i accept 2>/dev/null || true
PostUp = nft add rule ip amoscloud forward oifname %i ct state established,related accept 2>/dev/null || true
PostUp = nft add rule ip amoscloud postrouting oifname {config.wan_interface} masquerade 2>/dev/null || true
PostDown = nft delete table ip amoscloud 2>/dev/null || true

[Peer]
PublicKey = {validate_key('client public key', config.client_public_key)}
AllowedIPs = {client_ip}/32
"""


def render_client(config: GatewayConfig) -> str:
    client_ip = config.tunnel_network.network_address + 2
    return f"""[Interface]
Address = {client_ip}/{config.tunnel_network.prefixlen}
PrivateKey = {validate_key('client private key', config.client_private_key)}
DNS = {config.dns}

[Peer]
PublicKey = {validate_key('server public key', config.server_public_key)}
Endpoint = {config.endpoint}:{config.listen_port}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an authorized Amosclaud WireGuard gateway and client configuration"
    )
    parser.add_argument("--server-private-key", required=True)
    parser.add_argument("--server-public-key", required=True)
    parser.add_argument("--client-private-key", required=True)
    parser.add_argument("--client-public-key", required=True)
    parser.add_argument("--endpoint", required=True, help="VPS DNS name or public IP")
    parser.add_argument("--dns", default="1.1.1.1")
    parser.add_argument("--network", default="10.77.0.0/24")
    parser.add_argument("--wan-interface", default="eth0")
    parser.add_argument("--listen-port", type=int, default=51820)
    parser.add_argument("--output", type=Path, default=Path("generated-wireguard"))
    args = parser.parse_args()

    network = ipaddress.ip_network(args.network, strict=True)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 tunnel networks are supported in this milestone")
    if network.num_addresses < 4:
        raise ValueError("Tunnel network must provide at least four addresses")
    if not 1 <= args.listen_port <= 65535:
        raise ValueError("Listen port must be between 1 and 65535")

    config = GatewayConfig(
        server_private_key=args.server_private_key,
        server_public_key=args.server_public_key,
        client_private_key=args.client_private_key,
        client_public_key=args.client_public_key,
        endpoint=args.endpoint,
        dns=args.dns,
        tunnel_network=network,
        wan_interface=args.wan_interface,
        listen_port=args.listen_port,
    )

    args.output.mkdir(parents=True, exist_ok=True)
    server_path = args.output / "wg0-server.conf"
    client_path = args.output / "amosclaud-client.conf"
    server_path.write_text(render_server(config), encoding="utf-8")
    client_path.write_text(render_client(config), encoding="utf-8")
    server_path.chmod(0o600)
    client_path.chmod(0o600)
    print(f"Created {server_path}")
    print(f"Created {client_path}")


if __name__ == "__main__":
    main()
