# Amosclaud Authorized Internet Gateway

This milestone creates an encrypted path from a local Amosclaud network to a Linux VPS that already has legitimate public internet connectivity.

```text
Local device or Amosclaud router
              |
       WireGuard tunnel
              |
       Amosclaud VPS gateway
              |
     Authorized public internet
```

It does not create free carrier access, alter a SIM, inject unauthorized routes, or announce third-party address space.

## Requirements

- one Ubuntu VPS with a public IPv4 address
- permission from the VPS provider to use it as a VPN gateway
- UDP port `51820` allowed by the provider firewall
- WireGuard installed on the local computer or router
- root access to the VPS

## 1. Generate keys

Run separately on the VPS and local computer so private keys do not need to leave their machines:

```bash
umask 077
wg genkey | tee private.key | wg pubkey > public.key
```

Never commit private keys to GitHub.

## 2. Generate configurations

From the repository root:

```bash
python network/gateway/generate_wireguard.py \
  --server-private-key "$(cat server-private.key)" \
  --server-public-key "$(cat server-public.key)" \
  --client-private-key "$(cat client-private.key)" \
  --client-public-key "$(cat client-public.key)" \
  --endpoint gateway.example.com \
  --wan-interface eth0
```

The generator creates:

- `generated-wireguard/wg0-server.conf`
- `generated-wireguard/amosclaud-client.conf`

Confirm the VPS internet interface name with:

```bash
ip route show default
```

Use that interface for `--wan-interface`.

## 3. Install the VPS gateway

Copy only `wg0-server.conf` to the VPS, then run:

```bash
sudo bash network/gateway/install_ubuntu_gateway.sh ./wg0-server.conf
```

The installer enables IPv4 forwarding, WireGuard, and a restricted nftables forwarding/NAT table.

## 4. Connect the client

Import `amosclaud-client.conf` into the official WireGuard client on the local computer or supported router and activate it.

Test:

```bash
ping 10.77.0.1
curl https://example.com
```

## Safety defaults

- private keys are required at generation time and are never included in the repository
- generated files are written with mode `0600`
- the gateway forwards only traffic entering through its WireGuard interface
- arbitrary command execution is not part of this milestone
- only address space assigned to this private tunnel is configured

## What this provides

- encrypted remote path for Amosclaud traffic
- one controlled public exit point
- stable gateway for the Local Matrix Agent
- a foundation for health checks, failover, and later multi-site routing

## What comes next

- pair the Local Matrix Agent with the gateway
- add signed health reports and reconnect commands
- support split tunneling and per-service routing
- add multiple authorized sites
- expose gateway health in the Amosclaud admin dashboard
