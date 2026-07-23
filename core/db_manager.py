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
        conn.commit()
    logger.info("SQLite database initialized at: %s", DB_PATH)


def is_processed(video_id: str) -> bool:
    """
    Checks if a video has already been processed or is currently processing.
    
    Returns:
        bool: True if video_id exists with status 'COMPLETED' or 'PROCESSING'.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM processed_videos WHERE video_id = ?",
            (video_id,)
        )
        row = cursor.fetchone()
        if row:
            status = row["status"]
            return status in ("COMPLETED", "PROCESSING")
        return False


def mark_status(video_id: str, status: str, error_message: Optional[str] = None) -> None:
    """
    Inserts or updates the status of a video in the database.
    
    Args:
        video_id: Unique YouTube video ID.
        status: One of 'PROCESSING', 'COMPLETED', or 'FAILED'.
        error_message: Optional error message string if status is 'FAILED'.
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
