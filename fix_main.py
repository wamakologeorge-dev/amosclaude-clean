from amoscloud_ai.api.routes import logs, artifacts

# Add these lines with the other router includes:
app.include_router(logs.router, prefix="/api/v1")
app.include_router(artifacts.router, prefix="/api/v1")
with open('src/amoscloud_ai/main.py', 'r') as f:
    content = f.read()

