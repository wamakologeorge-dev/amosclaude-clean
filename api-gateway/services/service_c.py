# amos-api-gateway/services/service_c.py
from fastapi import FastAPI, status, HTTPException, Request
from fastapi.responses import JSONResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Service C")

@app.get("/")
async def read_root():
    return {"message": "Hello from Service C Root!"}

@app.delete("/delete/{item_id}")
async def delete_item_c(item_id: int, request: Request):
    logger.info(f"Service C received DELETE /delete/{item_id} from {request.client.host}")
    return {"service": "Service C", "status": f"item {item_id} deleted"}

@app.get("/status")
async def get_status_c(request: Request):
    logger.info(f"Service C received GET /status from {request.client.host}")
    return {"service": "Service C", "status": "operational", "load": "low"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
