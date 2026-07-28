"""
Database state manager for tracking processed YouTube videos in SQLite.
Ensures zero duplicate video processing and thread-safe status updates.
"""

import sqlite3
import logging
from typing import Optional
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with timeout and ROW factory configured."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def purge_invalid_clips() -> None:
    """Purges any database clip records whose MP4 file is missing or corrupted (< 100KB)."""
    from config import CLIPS_DIR
    import os
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clip_id, clip_path FROM clips")
        rows = cursor.fetchall()
        for row in rows:
            clip_id = row["clip_id"]
            clip_filename = row["clip_path"]
            file_path = CLIPS_DIR / clip_filename
            if not os.path.exists(file_path) or os.path.getsize(file_path) < 100000:
                logger.warning("Purging invalid/corrupted clip record '%s' (File: %s)", clip_id, file_path)
                cursor.execute("DELETE FROM clips WHERE clip_id = ?", (clip_id,))
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
        conn.commit()


def init_db() -> None:
    """Initializes the database schema if it does not already exist and purges invalid clips."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_videos (
                video_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('PROCESSING', 'COMPLETED', 'FAILED')),
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_message TEXT
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS clips (
                clip_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                video_title TEXT,
                clip_title TEXT NOT NULL,
                caption TEXT NOT NULL,
                hashtags TEXT NOT NULL,
                viral_score INTEGER NOT NULL,
                duration REAL NOT NULL,
                clip_path TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('READY', 'POSTED', 'ARCHIVED')) DEFAULT 'READY',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'custom',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                level TEXT NOT NULL CHECK(level IN ('INFO', 'WARNING', 'ERROR')),
                step TEXT,
                message TEXT NOT NULL,
                traceback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Ensure default active_mode setting is initialized
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('active_mode', 'PODCAST')")
        conn.commit()
    logger.info("SQLite database initialized at: %s", DB_PATH)

    try:
        purge_invalid_clips()
    except Exception as e:
        logger.warning("Failed to run purge_invalid_clips: %s", str(e))


def reset_video_state(video_id: str) -> None:
    """Deletes old processed_videos and system_logs for a video_id to retry cleanly."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM processed_videos WHERE video_id = ?", (video_id,))
        cursor.execute("DELETE FROM system_logs WHERE video_id = ?", (video_id,))
        conn.commit()
    logger.info("Reset DB processing state and logs for video_id '%s'", video_id)


def add_candidate_video(video_id: str, title: str, url: str, source: str = "custom") -> None:
    """Inserts or replaces a candidate video in SQLite DB."""
    reset_video_state(video_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO candidate_videos (video_id, title, url, source) VALUES (?, ?, ?, ?)",
            (video_id, title, url, source)
        )
        conn.commit()
    logger.info("Added candidate video '%s' (%s) to DB", video_id, source)



def get_unprocessed_custom_candidates() -> list[dict]:
    """Retrieves list of custom candidate videos that are not completed or failed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.video_id, c.title, c.url 
            FROM candidate_videos c
            LEFT JOIN processed_videos p ON c.video_id = p.video_id
            WHERE p.video_id IS NULL
            ORDER BY c.created_at ASC
            """
        )
        rows = cursor.fetchall()
        return [{"id": row["video_id"], "title": row["title"], "url": row["url"]} for row in rows]



def get_setting(key: str, default_value: str = "") -> str:
    """Retrieves a setting value by key from SQLite settings table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row["value"]
    return default_value


def set_setting(key: str, value: str) -> None:
    """Sets/updates a setting key-value pair in SQLite settings table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    logger.info("Updated setting '%s' -> '%s'", key, value)




def is_processed(video_id: str) -> bool:
    """
    Checks if a video has already been completed successfully.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM processed_videos WHERE video_id = ?",
            (video_id,)
        )
        row = cursor.fetchone()
        if row:
            return row["status"] == "COMPLETED"
        return False


def mark_status(video_id: str, status: str, error_message: Optional[str] = None) -> None:
    """
    Inserts or updates the status of a video in the database.
    """
    valid_statuses = {"PROCESSING", "COMPLETED", "FAILED"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO processed_videos (video_id, status, error_message, processed_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(video_id) DO UPDATE SET
                status = excluded.status,
                error_message = excluded.error_message,
                processed_at = CURRENT_TIMESTAMP;
            """,
            (video_id, status, error_message)
        )
        conn.commit()
    logger.info("Updated video_id '%s' status to '%s'", video_id, status)


def save_clip(
    clip_id: str,
    video_id: str,
    video_title: str,
    clip_title: str,
    caption: str,
    hashtags: str,
    viral_score: int,
    duration: float,
    clip_path: str
) -> None:
    """Saves a newly rendered high-viral clip into the SQLite database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO clips (
                clip_id, video_id, video_title, clip_title, caption,
                hashtags, viral_score, duration, clip_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY')
            ON CONFLICT(clip_id) DO UPDATE SET
                clip_title = excluded.clip_title,
                caption = excluded.caption,
                hashtags = excluded.hashtags,
                viral_score = excluded.viral_score,
                duration = excluded.duration,
                clip_path = excluded.clip_path;
            """,
            (clip_id, video_id, video_title, clip_title, caption, hashtags, viral_score, duration, clip_path)
        )
        conn.commit()
    logger.info("Saved clip '%s' (Score: %d) to database", clip_id, viral_score)


def get_clips(status: Optional[str] = None, min_score: Optional[int] = None) -> list[dict]:
    """Retrieves clips from the database with optional status and score filtering."""
    query = "SELECT * FROM clips"
    params = []
    conditions = []

    if status and status != "ALL":
        conditions.append("status = ?")
        params.append(status)
    if min_score is not None:
        conditions.append("viral_score >= ?")
        params.append(min_score)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_clip_by_id(clip_id: str) -> Optional[dict]:
    """Fetches a single clip by its unique clip_id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_clip_status(clip_id: str, status: str) -> bool:
    """Updates the status of a clip ('READY', 'POSTED', 'ARCHIVED')."""
    valid_statuses = {"READY", "POSTED", "ARCHIVED"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid clip status '{status}'. Must be one of {valid_statuses}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE clips SET status = ? WHERE clip_id = ?", (status, clip_id))
        conn.commit()
        return cursor.rowcount > 0


def delete_clip_db(clip_id: str) -> Optional[str]:
    """Deletes clip record from DB and returns its clip_path for disk removal."""
    clip = get_clip_by_id(clip_id)
    if not clip:
        return None
    clip_path = clip.get("clip_path")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM clips WHERE clip_id = ?", (clip_id,))
        conn.commit()
    return clip_path


def get_dashboard_stats() -> dict:
    """Calculates summary statistics for the web PWA dashboard."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM clips")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) as ready FROM clips WHERE status = 'READY'")
        ready = cursor.fetchone()["ready"]

        cursor.execute("SELECT COUNT(*) as posted FROM clips WHERE status = 'POSTED'")
        posted = cursor.fetchone()["posted"]

        cursor.execute("SELECT AVG(viral_score) as avg_score FROM clips")
        avg_row = cursor.fetchone()
        avg_score = round(avg_row["avg_score"] or 0, 1)

        return {
            "total_clips": total,
            "ready_to_post": ready,
            "ready_clips": ready,
            "posted": posted,
            "posted_clips": posted,
            "avg_viral_score": avg_score
        }


def add_system_log(video_id: Optional[str], level: str, step: str, message: str, traceback_str: Optional[str] = None) -> None:
    """Inserts a structured diagnostic/progress system log entry into SQLite DB."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO system_logs (video_id, level, step, message, traceback)
                VALUES (?, ?, ?, ?, ?)
                """,
                (video_id, level, step, message, traceback_str)
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to insert system log into DB: %s", str(e))


def get_system_logs(limit: int = 50, video_id: Optional[str] = None) -> list[dict]:
    """Retrieves list of system diagnostic logs."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if video_id:
                cursor.execute(
                    "SELECT * FROM system_logs WHERE video_id = ? ORDER BY id DESC LIMIT ?",
                    (video_id, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM system_logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def get_vps_storage_info() -> dict:
    """
    Scans VPS storage (temp/ and output_clips/) and database records.
    Returns disk usage stats, list of downloaded source videos in temp/, and clips.
    """
    import shutil
    import os
    from config import TEMP_DIR, CLIPS_DIR, BASE_DIR

    total_b, used_b, free_b = shutil.disk_usage(str(BASE_DIR))
    
    temp_size_b = 0
    if os.path.exists(TEMP_DIR):
        for f in os.listdir(TEMP_DIR):
            fp = os.path.join(TEMP_DIR, f)
            if os.path.isfile(fp):
                temp_size_b += os.path.getsize(fp)

    clips_size_b = 0
    if os.path.exists(CLIPS_DIR):
        for f in os.listdir(CLIPS_DIR):
            fp = os.path.join(CLIPS_DIR, f)
            if os.path.isfile(fp):
                clips_size_b += os.path.getsize(fp)

    videos_map = {}
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT video_id, title, url, source, created_at FROM candidate_videos ORDER BY created_at DESC")
        for row in cursor.fetchall():
            v_id = row["video_id"]
            videos_map[v_id] = {
                "video_id": v_id,
                "title": row["title"],
                "url": row["url"],
                "source": row["source"],
                "created_at": row["created_at"],
                "status": "IDLE",
                "video_file_mb": 0.0,
                "audio_file_mb": 0.0,
                "total_source_mb": 0.0,
                "clips_count": 0,
                "clips_total_mb": 0.0,
                "has_source": False
            }

        cursor.execute("SELECT video_id, status, processed_at, error_message FROM processed_videos")
        for row in cursor.fetchall():
            v_id = row["video_id"]
            if v_id not in videos_map:
                videos_map[v_id] = {
                    "video_id": v_id,
                    "title": f"Video ({v_id})",
                    "url": f"https://www.youtube.com/watch?v={v_id}",
                    "source": "custom",
                    "created_at": row["processed_at"],
                    "status": row["status"],
                    "video_file_mb": 0.0,
                    "audio_file_mb": 0.0,
                    "total_source_mb": 0.0,
                    "clips_count": 0,
                    "clips_total_mb": 0.0,
                    "has_source": False
                }
            else:
                videos_map[v_id]["status"] = row["status"]

        cursor.execute("SELECT video_id, clip_path FROM clips")
        for row in cursor.fetchall():
            v_id = row["video_id"]
            c_file = row["clip_path"]
            if v_id in videos_map:
                videos_map[v_id]["clips_count"] += 1
                c_path = CLIPS_DIR / c_file
                if os.path.exists(c_path):
                    videos_map[v_id]["clips_total_mb"] += round(os.path.getsize(c_path) / (1024 * 1024), 2)

    if os.path.exists(TEMP_DIR):
        for fname in os.listdir(TEMP_DIR):
            f_path = os.path.join(TEMP_DIR, fname)
            if not os.path.isfile(f_path):
                continue
            f_size_mb = round(os.path.getsize(f_path) / (1024 * 1024), 2)

            v_id = fname.split("_")[0]
            if v_id in videos_map:
                videos_map[v_id]["has_source"] = True
                videos_map[v_id]["total_source_mb"] += f_size_mb
                if fname.endswith("_video.mp4"):
                    videos_map[v_id]["video_file_mb"] = f_size_mb
                elif fname.endswith("_audio.wav"):
                    videos_map[v_id]["audio_file_mb"] = f_size_mb

    v_list = list(videos_map.values())

    return {
        "disk_total_gb": round(total_b / (1024**3), 2),
        "disk_used_gb": round(used_b / (1024**3), 2),
        "disk_free_gb": round(free_b / (1024**3), 2),
        "bot_temp_mb": round(temp_size_b / (1024**2), 2),
        "bot_clips_mb": round(clips_size_b / (1024**2), 2),
        "bot_total_mb": round((temp_size_b + clips_size_b) / (1024**2), 2),
        "videos": v_list
    }


def delete_vps_source_video(video_id: str) -> dict:
    """
    Deletes all temporary source video/audio files AND rendered clips for video_id from disk
    and purges all database records in candidate_videos, processed_videos, clips, system_logs.
    Frees up VPS storage space immediately!
    """
    import os
    import glob
    from config import TEMP_DIR, CLIPS_DIR

    freed_bytes = 0
    deleted_files = []

    if os.path.exists(TEMP_DIR):
        pattern = os.path.join(TEMP_DIR, f"{video_id}*")
        for fp in glob.glob(pattern):
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                try:
                    os.remove(fp)
                    freed_bytes += sz
                    deleted_files.append(os.path.basename(fp))
                except Exception as e:
                    logger.warning("Failed to remove temp file %s: %s", fp, str(e))

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clip_path FROM clips WHERE video_id = ?", (video_id,))
        clip_rows = cursor.fetchall()
        for r in clip_rows:
            c_file = r["clip_path"]
            c_path = CLIPS_DIR / c_file
            if os.path.exists(c_path):
                sz = os.path.getsize(c_path)
                try:
                    os.remove(c_path)
                    freed_bytes += sz
                    deleted_files.append(c_file)
                except Exception as e:
                    logger.warning("Failed to remove clip file %s: %s", c_path, str(e))

        try:
            cursor.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
            cursor.execute("DELETE FROM processed_videos WHERE video_id = ?", (video_id,))
            cursor.execute("DELETE FROM candidate_videos WHERE video_id = ?", (video_id,))
            cursor.execute("DELETE FROM system_logs WHERE video_id = ?", (video_id,))
            conn.commit()
        except Exception as db_err:
            conn.rollback()
            logger.error("Failed DB deletion transaction for video_id '%s': %s", video_id, str(db_err))
            raise db_err

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    logger.info("Deleted video_id '%s' and freed %.2f MB on VPS storage", video_id, freed_mb)
    return {"video_id": video_id, "freed_mb": freed_mb, "deleted_files": deleted_files}

