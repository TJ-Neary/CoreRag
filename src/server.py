from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn
import logging
import os

from src.staging import get_pending_items, update_item, get_item
from src.executor import execute_approved_item

# Logging
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "ui" / "templates"
STATIC_DIR = BASE_DIR / "ui" / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/queue")
async def get_queue():
    return get_pending_items()

@app.post("/api/update/{item_id}")
async def update_queue_item(item_id: str, updates: dict):
    success = update_item(item_id, updates)
    return {"success": success}

@app.post("/api/approve/{item_id}")
async def approve_queue_item(item_id: str, background_tasks: BackgroundTasks):
    # Mark as approved
    update_item(item_id, {"status": "approved"})
    
    # Trigger execution in background to stay responsive
    background_tasks.add_task(execute_approved_item, item_id)
    
    return {"status": "approved", "message": "Processing started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
