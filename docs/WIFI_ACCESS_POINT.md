# Amosclaud managed Wi-Fi access point

This integration connects Amosclaud to a MikroTik RouterOS 7 device through the RouterOS REST API. The administrator dashboard also runs bounded diagnostics across the local router, DNS, public internet, and the Amosclaud network server service.

## Railway variables

Set these on the Amosclaud web service:

- `AMOS_ADMIN_KEY`: long random secret used in the `X-Admin-Key` request header
- `MIKROTIK_BASE_URL`: for example `https://192.168.88.1`
- `MIKROTIK_USERNAME`: limited RouterOS service account
- `MIKROTIK_PASSWORD`: password for that service account
- `MIKROTIK_VERIFY_TLS`: `true` for a trusted certificate; use `false` only during local testing
- `MIKROTIK_WIFI_INTERFACE_ID`: RouterOS Wi-Fi interface id, commonly `wifi1`
- `MIKROTIK_WIFI_SECURITY_ID`: RouterOS Wi-Fi security profile id, commonly `default`

Optional network-diagnostics variables:

- `AMOSCLAUD_NETWORK_SERVICE_HEALTH_URL`: full health URL for a separate Amosclaud network server service, such as `https://network.example.com/ready`
- `AMOSCLAUD_NETWORK_DIAGNOSTIC_HOST`: hostname used for the DNS test; when omitted, Amosclaud derives it from the configured health or internet-probe URL
- `AMOSCLAUD_NETWORK_INTERNET_PROBE_URL`: bounded HTTP probe target; defaults to `https://www.amosclaud.com/health`
- `AMOSCLAUD_NETWORK_DIAGNOSTIC_TIMEOUT`: timeout per DNS or HTTP probe in seconds; defaults to `5` and is capped at `15`
- `AMOSCLAUD_NETWORK_OWNER_USER_ID`: owner whose registered model stations supply the local Amosclaud model-network readiness signal

The remote network-service URL is optional. Amosclaud always checks its local model-network service first and combines that result with the remote health probe when one is configured.

## API endpoints

All endpoints require `X-Admin-Key`.

- `GET /api/v1/admin/wifi/status`
- `GET /api/v1/admin/wifi/devices`
- `GET /api/v1/admin/wifi/diagnostics`
- `PUT /api/v1/admin/wifi/network`

The diagnostics response contains five ordered checks:

1. Local Network
2. Name Resolution
3. Wi-Fi
4. Internet Connectivity
5. Amosclaud Network Service

Each check reports `passed`, `failed`, or `skipped`, with bounded latency evidence. The response never returns router credentials, Wi-Fi passwords, admin keys, or configured endpoint URLs.

Example update body:

```json
{
  "ssid": "Amosclaud-Admin",
  "password": "replace-with-a-strong-password",
  "disabled": false
}
```

## Administrator dashboard

Sign in with an Amosclaud administrator account and open `/admin/wifi`. Enter the `AMOS_ADMIN_KEY`, then choose **Connect** or **Run diagnostics**. The page displays the connection path, SSID, channel, connected-device count, and ready model-station count without exposing secrets.

## RouterOS preparation

1. Upgrade the MikroTik device to a current RouterOS 7 release.
2. Enable HTTPS access to the RouterOS REST API.
3. Create a dedicated service account for Amosclaud. Do not use the router's main administrator account.
4. Restrict that account and firewall access so only the Amosclaud server or private VPN can reach the management interface.
5. Use a trusted TLS certificate before production use.

## Security notes

Never commit router credentials, Wi-Fi passwords, network-service secrets, or the admin key to GitHub. Store them only as Railway secrets. Keep the RouterOS management interface private; do not expose it directly to the public internet.

The diagnostics page is based on the connection-test flow shown in the provided screenshot, but the screenshot itself is not committed because it contains private local-network identifiers such as an SSID, IP address, BSSID, and MAC address.
