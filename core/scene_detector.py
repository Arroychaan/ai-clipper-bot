"""
PySceneDetect Scene-Aware Cutting Engine.

Detects natural scene boundaries (hard cuts, fades, transitions) in video files
using PySceneDetect ContentDetector. Provides frame-accurate scene timestamps
for intelligent clip boundary snapping — prevents cutting in the middle of
OBS scene transitions or camera switches.

Lightweight: ~50-80 MB RAM. Feasible on VPS 2GB.
"""

import os
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SceneBoundary:
    """A detected scene transition point."""
    timestamp_sec: float
    frame_number: int
    score: float  # Content change score (0.0 - 1.0)


def detect_scene_boundaries(
    video_path: str,
    threshold: float = 27.0,
    min_scene_len_sec: float = 2.0,
) -> List[SceneBoundary]:
    """
    Detects all scene boundaries in a video file using PySceneDetect ContentDetector.

    Args:
        video_path: Path to the input video file.
        threshold: ContentDetector sensitivity (lower = more sensitive). Default 27.0.
        min_scene_len_sec: Minimum scene length in seconds. Default 2.0s.

    Returns:
        List of SceneBoundary objects sorted by timestamp.
    """
    if not os.path.exists(video_path):
        logger.warning("Video file does not exist for scene detection: %s", video_path)
        return []

    try:
        from scenedetect import detect, ContentDetector  # type: ignore

        # Convert min_scene_len from seconds to frames (assume ~30fps as safe default)
        min_scene_len_frames = max(1, int(min_scene_len_sec * 30))

        scene_list = detect(
            video_path,
            ContentDetector(
                threshold=threshold,
                min_scene_len=min_scene_len_frames
            )
        )

        boundaries: List[SceneBoundary] = []
        for scene_start, scene_end in scene_list:
            # Scene boundary is at scene_start (the first frame of a new scene)
            ts = scene_start.get_seconds()
            frame = scene_start.get_frames()
            # PySceneDetect doesn't directly expose the score per boundary in this API,
            # so we use 1.0 as a placeholder for detected boundaries
            boundaries.append(SceneBoundary(
                timestamp_sec=round(ts, 3),
                frame_number=frame,
                score=1.0
            ))

        logger.info(
            "🎬 PySceneDetect found %d scene boundaries in %s (threshold=%.1f)",
            len(boundaries), os.path.basename(video_path), threshold
        )
        return boundaries

    except ImportError:
        logger.warning(
            "PySceneDetect is not installed. Install with: pip install scenedetect[opencv]"
        )
        return []
    except Exception as e:
        logger.error("Scene detection failed: %s", str(e))
        return []


def snap_to_nearest_scene_boundary(
    target_sec: float,
    boundaries: List[SceneBoundary],
    max_snap_distance_sec: float = 3.0,
    prefer_direction: str = "nearest"
) -> float:
    """
    Snaps a timestamp to the nearest scene boundary, if one exists within max_snap_distance.

    This prevents clips from starting/ending in the middle of an OBS scene transition
    or camera switch. Instead, the cut happens exactly at the natural scene change.

    Args:
        target_sec: The original timestamp to snap.
        boundaries: List of detected scene boundaries.
        max_snap_distance_sec: Maximum distance to snap (default 3.0s).
        prefer_direction: 'before' (snap to earlier boundary), 'after' (snap to later),
                          or 'nearest' (snap to closest).

    Returns:
        Snapped timestamp, or original if no boundary is close enough.
    """
    if not boundaries:
        return target_sec

    best_ts = target_sec
    best_distance = float("inf")

    for b in boundaries:
        distance = abs(b.timestamp_sec - target_sec)
        if distance > max_snap_distance_sec:
            continue

        if prefer_direction == "before" and b.timestamp_sec > target_sec:
            continue
        if prefer_direction == "after" and b.timestamp_sec < target_sec:
            continue

        if distance < best_distance:
            best_distance = distance
            best_ts = b.timestamp_sec

    if best_ts != target_sec:
        logger.info(
            "🎯 Snapped timestamp %.2fs → %.2fs (scene boundary, shift: %+.2fs)",
            target_sec, best_ts, best_ts - target_sec
        )

    return best_ts


def find_scene_boundaries_in_range(
    boundaries: List[SceneBoundary],
    start_sec: float,
    end_sec: float
) -> List[SceneBoundary]:
    """
    Returns all scene boundaries that fall within a given time range.

    Useful for understanding the internal structure of a selected clip —
    how many scene changes happen within the clip, and where.

    Args:
        boundaries: Full list of detected scene boundaries.
        start_sec: Range start.
        end_sec: Range end.

    Returns:
        Filtered list of boundaries within [start_sec, end_sec].
    """
    return [
        b for b in boundaries
        if start_sec <= b.timestamp_sec <= end_sec
    ]

