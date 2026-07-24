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


def init_db() -> None:
    """Initializes the database schema if it does not already exist."""
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
        conn.commit()
    logger.info("SQLite database initialized at: %s", DB_PATH)


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
            "ready_clips": ready,
            "posted_clips": posted,
            "avg_viral_score": avg_score
        }

