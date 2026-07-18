from fastapi import FastAPI
from database.models import Base
from repository.git_server import router as git_router

app = FastAPI(title="Amosclaud Core Engine Platform")

# Register the custom Git HTTP Hosting network gateway routes
app.include_router(git_router)
