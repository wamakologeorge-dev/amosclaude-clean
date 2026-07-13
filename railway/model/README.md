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
5. Set `AMOSCLAUD_MODEL=qwen2.5-coder:3b` or another model that fits the available memory.
6. Deploy and wait for `/api/tags` to pass the health check.

## Backend connection

In the existing backend service, set:

```text
AMOSCLAUD_MODEL_URL=http://${{RAILWAY_PRIVATE_DOMAIN}}:11434
AMOSCLAUD_MODEL=qwen2.5-coder:3b
AMOSCLAUD_MODEL_TIMEOUT=120
AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS=false
```

Use Railway's variable reference UI to point `AMOSCLAUD_MODEL_URL` at the model
service's private domain. Do not copy a public URL and do not expose port 11434
outside the project.

After saving the variables, redeploy the backend and test `/api/chat`.

## Capacity note

A local coding model requires substantially more memory than the API service.
If the service is repeatedly killed or restarts during model load, increase the
Railway memory allocation or select a smaller quantized model. The default 3B
model is chosen to reduce the initial resource requirement, not because it is a
fully trained proprietary Amosclaud foundation model.
