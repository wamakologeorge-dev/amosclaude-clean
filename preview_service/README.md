# Amosclaud Dedicated Preview Service

This service accepts verified static-site ZIP archives from the background worker
and serves them without executing uploaded code.

## Required variables

```text
AMOSCLAUD_PREVIEW_SERVICE_KEY=<independent-random-secret>
AMOSCLAUD_PREVIEW_DATA=/data/previews
PORT=8080
```

The worker uses the same service key and sets:

```text
AMOSCLAUD_PREVIEW_SERVICE_URL=http://preview-service:8080
```

Deploy the service separately from the main Amosclaud API. Attach persistent
storage at `/data/previews` and put a reverse proxy in front of the service.
`Caddyfile` is a starting template.

## Publishing contract

`POST /internal/previews` requires `X-Amosclaud-Preview-Key` and accepts:

- `owner_user_id`
- `run_id`
- a bounded ZIP archive containing `index.html`

The archive is rejected if it contains traversal paths, symlinks, non-static file
types, too many files, or an unsafe expansion size.

## Custom domains

Custom domains are created through the internal domain endpoint. The service
returns an `_amosclaud-preview.<domain>` TXT record. Traffic is served for the
hostname only after the verification endpoint confirms that exact token in DNS.
