# Railway Amosclaud model service

This directory deploys the private model runtime used by the Amosclaud backend.
The service runs Ollama as infrastructure, downloads the configured coding model,
and exposes an OpenAI-compatible endpoint to the backend over Railway's private
network. Users still interact with Amosclaud as the provider.

## Railway service setup

1. Create a new Railway service from this repository.
2. Set the service root directory to `railway/model`.
3. Keep the service private; do not generate a public domain.
4. Attach a persistent volume at `/root/.ollama` so model files survive restarts.
5. Keep the default `AMOSCLAUD_MODEL=qwen2.5-coder:1.5b`, or select a model
   that fits the available memory.
6. Deploy and wait for `/api/tags` to pass the health check.

## Backend connection

In the existing backend service, set:

```text
AMOSCLAUD_MODEL_URL=http://<service>.railway.internal:11434
AMOSCLAUD_MODEL=qwen2.5-coder:1.5b
AMOSCLAUD_MODEL_TIMEOUT=120
AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS=false
```

Replace `<service>` with the Railway model service's private service name. The
URL must be the full private URL, including the `http://` scheme and `:11434`
port. A bare hostname without a scheme or port fails DNS resolution. Use
Railway's variable reference UI to supply the private domain; do not copy a
public URL or expose port 11434 outside the project.

After saving the variables, redeploy the backend and test `/api/chat`.

## Model sizing

The following measurements were taken while the real model service was serving
requests. Peak resident memory includes the model runtime overhead, not only
model weights.

| Model | Download | Measured peak resident memory while serving | Deployment guidance |
| --- | ---: | ---: | --- |
| `qwen2.5-coder:0.5b` | 397 MB | ~545 MB | Fits a 1 GB container. |
| `qwen2.5-coder:1.5b` (default) | 986 MB | ~1.2 GB | Fits a 2 GB container. |
| `qwen2.5-coder:3b` | 1.9 GB | n/a | Requires at least 4 GB; it will crash-loop below that. |

`qwen2.5-coder:1.5b` is the safe default for a first deployment. Override it
without rebuilding by setting `AMOSCLAUD_MODEL` on both the model service and
backend to the same model name. The 3B model was reproducibly OOM-killed below
about 3.8 GB of RAM; its tensor buffers alone require about 1.83 GB before KV
cache and runtime overhead.
