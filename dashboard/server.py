"""
FastAPI Server for PWA Web Dashboard of ai-clipper-bot.
Provides static asset hosting, video clip streaming, and REST API endpoints for clip management.
"""

import os
import sys
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Response, Depends, status, BackgroundTasks
from pydantic import BaseModel
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
    get_dashboard_stats,
    get_setting,
    set_setting
)
from pydantic import BaseModel


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


# --- DASHBOARD & ADMIN PAGES ---

@app.get("/", response_class=HTMLResponse)
def get_dashboard_html():
    """Serves the main PWA Dashboard HTML interface."""
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard template index.html not found")
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/admin", response_class=HTMLResponse)
def get_admin_html():
    """Serves the Admin System Log Inspector HTML interface."""
    admin_file = TEMPLATES_DIR / "admin.html"
    if not admin_file.exists():
        raise HTTPException(status_code=404, detail="Admin template admin.html not found")
    with open(admin_file, "r", encoding="utf-8") as f:
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


class CustomUrlPayload(BaseModel):
    url: str

@app.post("/api/clip-url")
def api_clip_custom_url(payload: CustomUrlPayload, background_tasks: BackgroundTasks):
    """Triggers instant processing for a specific YouTube VOD link (Wayin.ai style)."""
    raw_url = payload.url.strip()
    v_id = None
    if "v=" in raw_url:
        v_id = raw_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in raw_url:
        v_id = raw_url.split("youtu.be/")[1].split("?")[0]
    
    if not v_id:
        raise HTTPException(status_code=400, detail="Link YouTube tidak valid. Harap gunakan format link YouTube yang benar.")

    clean_url = f"https://www.youtube.com/watch?v={v_id}"
    
    from core.db_manager import add_candidate_video
    add_candidate_video(v_id, f"Custom VOD ({v_id})", clean_url, "custom")

    def _run_clip():
        try:
            from main import process_single_video
            from core.groq_manager import ResilientGroqClient
            from core.db_manager import get_setting
            groq_client = ResilientGroqClient()
            active_mode = get_setting("active_mode", "PODCAST")
            item = {"video_id": v_id, "title": f"Custom VOD ({v_id})", "url": clean_url}
            process_single_video(item, groq_client, force_gaming_mode=(active_mode == "WINDAH"))
        except Exception as e:
            print(f"[error] Custom URL clip background processing failed: {e}")

    background_tasks.add_task(_run_clip)
    return {"message": f"Link YouTube ID '{v_id}' berhasil masuk antrean klip instan!", "video_id": v_id}


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


class ModePayload(BaseModel):
    mode: str


@app.get("/api/mode")
def api_get_mode():
    """Gets current active mode setting ('PODCAST' or 'WINDAH')."""
    active_mode = get_setting("active_mode", "PODCAST")
    return {"mode": active_mode}


@app.post("/api/mode")
def api_set_mode(payload: ModePayload):
    """Sets active mode setting ('PODCAST' or 'WINDAH')."""
    target_mode = payload.mode.upper().strip()
    if target_mode not in ("PODCAST", "WINDAH"):
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'PODCAST' or 'WINDAH'")
    set_setting("active_mode", target_mode)
    return {"status": "success", "mode": target_mode}


# --- ADMIN LOG INSPECTOR API ENDPOINTS ---

@app.get("/api/admin/logs")
def api_get_admin_logs(level: str = Query("ALL"), limit: int = Query(300)):
    """Reads system log lines from LOG_FILE_PATH with optional filtering."""
    if not LOG_FILE_PATH.exists():
        return {"logs": [], "total_lines": 0, "error_count": 0, "warning_count": 0}

    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {e}")

    total_lines = len(lines)
    error_count = sum(1 for line in lines if any(k in line for k in ("ERROR", "CRITICAL", "Failed", "Exception")))
    warning_count = sum(1 for line in lines if "WARNING" in line)

    target_level = level.upper().strip()
    filtered_lines = []

    for line in reversed(lines):
        line_clean = line.rstrip()
        if not line_clean:
            continue

        if target_level == "ERROR":
            if any(k in line_clean for k in ("ERROR", "CRITICAL", "Failed", "Exception")):
                filtered_lines.append(line_clean)
        elif target_level == "WARNING":
            if "WARNING" in line_clean:
                filtered_lines.append(line_clean)
        else:
            filtered_lines.append(line_clean)

        if len(filtered_lines) >= limit:
            break

    filtered_lines.reverse()
    return {
        "logs": filtered_lines,
        "total_lines": total_lines,
        "error_count": error_count,
        "warning_count": warning_count
    }


@app.get("/api/admin/failed-videos")
def api_get_failed_videos():
    """Returns list of videos that failed during processing with their error messages."""
    from core.db_manager import get_connection
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.video_id, p.status, p.error_message, p.processed_at, c.title
            FROM processed_videos p
            LEFT JOIN candidate_videos c ON p.video_id = c.video_id
            WHERE p.status = 'FAILED'
            ORDER BY p.processed_at DESC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "video_id": row["video_id"],
                "status": row["status"],
                "error_message": row["error_message"],
                "processed_at": row["processed_at"],
                "title": row["title"] or f"Video ({row['video_id']})"
            }
            for row in rows
        ]


@app.post("/api/admin/clear-logs")
def api_clear_admin_logs():
    """Clears or truncates the server log file."""
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                f.write("")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear log file: {e}")
    return {"message": "Server log file cleared successfully"}


def run_dashboard():
    """Entry point for launching the dashboard server."""
    uvicorn.run("dashboard.server:app", host=DASHBOARD_HOST, port=DASHBOARD_PORT, reload=False)



if __name__ == "__main__":
    run_dashboard()
