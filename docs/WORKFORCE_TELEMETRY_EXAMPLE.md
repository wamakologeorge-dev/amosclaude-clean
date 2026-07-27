# Software Asset Telemetry Example

After registering an asset, Amosclaud returns a one-time token with the prefix `amos_asset_`. Store it in the asset's secret manager and send it only over HTTPS.

## Health and business sample

```bash
curl -X POST \
  "https://www.amosclaud.com/api/v1/workforce/assets/ASSET_ID/telemetry" \
  -H "Authorization: Bearer $AMOSCLAUD_ASSET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "online": true,
    "status_code": 200,
    "latency_ms": 42.8,
    "cpu_percent": 18.5,
    "memory_mb": 384,
    "error_count": 0,
    "request_count": 1720,
    "active_users": 36,
    "revenue_usd": 249.50,
    "metadata": {
      "release": "2026.07.27",
      "region": "local-station"
    }
  }'
```

## Operational event sample

```bash
curl -X POST \
  "https://www.amosclaud.com/api/v1/workforce/assets/ASSET_ID/events" \
  -H "Authorization: Bearer $AMOSCLAUD_ASSET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "severity": "warning",
    "event_type": "dependency.degraded",
    "message": "Payment provider latency exceeded the warning threshold.",
    "details": {
      "latency_ms": 1380,
      "automatic_action": "retry policy activated"
    }
  }'
```

Do not include API keys, authorization headers, passwords, cookies, or customer records in telemetry metadata. Amosclaud applies bounded recursive redaction, but the asset should avoid sending secrets in the first place.
