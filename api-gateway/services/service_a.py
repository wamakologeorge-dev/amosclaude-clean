# amos-api-gateway/services/service_a.py
from fastapi import FastAPI, status, HTTPException, Request
from fastapi.responses import JSONResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Service A")

@app.get("/")
async def read_root():
    return {"message": "Hello from Service A Root!"}

@app.get("/data")
async def get_data_a(request: Request):
    logger.info(f"Service A received GET /data from {request.client.host}")
    return {"service": "Service A", "data": "This is data from Service A"}

@app.post("/items")
async def create_item_a(item: dict, request: Request):
    logger.info(f"Service A received POST /items with data: {item} from {request.client.host}")
    return {"service": "Service A", "status": "item created", "item": item}

@app.get("/error")
async def simulate_error_a():
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Simulated error in Service A")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
