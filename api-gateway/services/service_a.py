# amos-api-gateway/services/service_b.py
from fastapi import FastAPI, status, HTTPException, Request
from fastapi.responses import JSONResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Service B")

@app.get("/")
async def read_root():
    return {"message": "Hello from Service B Root!"}

@app.get("/info")
async def get_info_b(request: Request):
    logger.info(f"Service B received GET /info from {request.client.host}")
    return {"service": "Service B", "info": "Information from Service B"}

@app.put("/update/{item_id}")
async def update_item_b(item_id: int, item: dict, request: Request):
    logger.info(f"Service B received PUT /update/{item_id} with data: {item} from {request.client.host}")
    return {"service": "Service B", "status": f"item {item_id} updated", "item": item}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
