# Amosclaud managed Wi-Fi access point

This integration connects Amosclaud to a MikroTik RouterOS 7 device through the RouterOS REST API.

## Railway variables

Set these on the Amosclaud web service:

- `AMOS_ADMIN_KEY`: long random secret used in the `X-Admin-Key` request header
- `MIKROTIK_BASE_URL`: for example `https://192.168.88.1`
- `MIKROTIK_USERNAME`: limited RouterOS service account
- `MIKROTIK_PASSWORD`: password for that service account
- `MIKROTIK_VERIFY_TLS`: `true` for a trusted certificate; use `false` only during local testing
- `MIKROTIK_WIFI_INTERFACE_ID`: RouterOS Wi-Fi interface id, commonly `wifi1`
- `MIKROTIK_WIFI_SECURITY_ID`: RouterOS Wi-Fi security profile id, commonly `default`

## API endpoints

All endpoints require `X-Admin-Key`.

- `GET /api/v1/admin/wifi/status`
- `GET /api/v1/admin/wifi/devices`
- `PUT /api/v1/admin/wifi/network`

Example update body:

```json
{
  "ssid": "Amosclaud-Admin",
  "password": "replace-with-a-strong-password",
  "disabled": false
}
```

## RouterOS preparation

1. Upgrade the MikroTik device to a current RouterOS 7 release.
2. Enable HTTPS access to the RouterOS REST API.
3. Create a dedicated service account for Amosclaud. Do not use the router's main administrator account.
4. Restrict that account and firewall access so only the Amosclaud server or private VPN can reach the management interface.
5. Use a trusted TLS certificate before production use.

## Security notes

Never commit router credentials or the admin key to GitHub. Store them only as Railway secrets. Keep the RouterOS management interface private; do not expose it directly to the public internet.
