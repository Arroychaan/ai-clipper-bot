"""
FastAPI Server for PWA Web Dashboard of ai-clipper-bot.
Provides static asset hosting, video clip streaming, and REST API endpoints for clip management.
"""

import os
import sys
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Response, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn

# Ensure parent directory is in Python path for imports
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import (
    CLIPS_DIR,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_PASSWORD
)
from core.db_manager import (
    init_db,
    get_clips,
    get_clip_by_id,
    update_clip_status,
    delete_clip_db,
    get_dashboard_stats
)

app = FastAPI(title="AI Clipper Bot PWA Dashboard", version="2.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

security = HTTPBasic()


def check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Optional basic authentication check if password is defined."""
    if DASHBOARD_PASSWORD and credentials.password != DASHBOARD_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.on_event("startup")
def on_startup():
    """Initializes SQLite database schema upon startup."""
    init_db()


@app.get("/", response_class=HTMLResponse)
def get_dashboard_html():
    """Serves the main PWA Dashboard HTML interface."""
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard template index.html not found")
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/manifest.json")
def get_manifest():
    """Serves the PWA Web App Manifest."""
    manifest_file = STATIC_DIR / "manifest.json"
    return FileResponse(manifest_file, media_type="application/manifest+json")


@app.get("/sw.js")
def get_service_worker():
    """Serves the PWA Service Worker script."""
    sw_file = STATIC_DIR / "sw.js"
    return FileResponse(sw_file, media_type="application/javascript")


@app.get("/clips/{filename}")
def get_clip_file(filename: str):
    """Streams MP4 video clip files directly from CLIPS_DIR."""
    file_path = CLIPS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Clip file '{filename}' not found")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)


# --- REST API ENDPOINTS ---

@app.get("/api/stats")
def api_get_stats():
    """Returns overall clipping stats."""
    return get_dashboard_stats()


@app.get("/api/clips")
def api_get_clips(status: Optional[str] = Query("READY")):
    """Returns list of clips filtered by status ('READY', 'POSTED', 'ALL')."""
    return get_clips(status=status)


@app.post("/api/clips/{clip_id}/status")
def api_update_clip_status(clip_id: str, status: str = Query(...)):
    """Updates status of a clip ('READY', 'POSTED', 'ARCHIVED')."""
    success = update_clip_status(clip_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="Clip ID not found")
    return {"message": "Status updated successfully", "clip_id": clip_id, "status": status}


@app.delete("/api/clips/{clip_id}")
def api_delete_clip(clip_id: str):
    """Deletes clip record from DB and deletes MP4 video file from disk."""
    clip_filename = delete_clip_db(clip_id)
    if not clip_filename:
        raise HTTPException(status_code=404, detail="Clip ID not found")

    file_path = CLIPS_DIR / clip_filename
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[warning] Failed to remove clip file '{file_path}': {e}")

    return {"message": "Clip deleted successfully", "clip_id": clip_id}


def run_dashboard():
    """Entry point for launching the dashboard server."""
    uvicorn.run("dashboard.server:app", host=DASHBOARD_HOST, port=DASHBOARD_PORT, reload=False)


if __name__ == "__main__":
    run_dashboard()
