# Amosclaud Bundles API Host

This service stores and serves versioned Amosclaud application bundles from persistent disk.
Every upload and download requires an Amosclaud API credential. Configure one of:

- `AMOSCLAUD_BUNDLES_API_KEY` (recommended dedicated host key)
- `AMOSCLAUD_API_KEY`
- `EXTERNAL_API_KEY`

Set `AMOSCLAUD_BUNDLE_ROOT=/data/bundles` and mount that path as a persistent volume. The host
uses the platform-provided `PORT`, falling back to `8080`.

Start locally with:

```bash
cp deploy/bundles-api-host/.env.example deploy/bundles-api-host/.env
docker compose -f deploy/bundles-api-host/docker-compose.yml up --build
```

Endpoints:

- `GET /api/v1/bundles/health` — public liveness
- `GET /api/v1/bundles` — authenticated catalog
- `POST /api/v1/bundles` — authenticated multipart upload
- `GET /api/v1/bundles/{bundle_id}` — authenticated metadata
- `GET /api/v1/bundles/{bundle_id}/download` — authenticated archive with SHA-256 headers

When the router is mounted in the full Amosclaud application, administrators can open the
interactive documentation dashboard at `/admin/bundles`.

Example upload:

```bash
curl -X POST http://localhost:8080/api/v1/bundles \
  -H "Authorization: Bearer $AMOSCLAUD_BUNDLES_API_KEY" \
  -F version=1.0.0 \
  -F platform=linux-x86_64 \
  -F channel=stable \
  -F file=@Amosclaud-Server.tar.gz
```
