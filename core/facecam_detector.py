"""
AI Facecam Detector module using OpenCV & Motion Variance Analysis.
Detects streamer facecam coordinates (x, y, w, h) in 16:9 gaming live streams (Windah Basudara style)
to dynamically crop the facecam for the Top Half (1080x960) of vertical 9:16 Shorts.
"""

import os
import logging
from typing import Tuple, Dict, Any, Optional, List

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore

logger = logging.getLogger(__name__)


def detect_streamer_facecam(
    video_path: str,
    sample_timestamps_sec: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Analyzes sample frames from a gaming live stream video file to locate the streamer's facecam box.
    Uses a 2-stage AI pipeline:
    1. Outer-Corner Restricted Haar Cascade Face Detection (ignores center game NPCs).
    2. Inter-Frame Motion Variance Analysis across outer corners.
    
    Returns:
        Dict containing crop parameters:
        {
            "crop_w": int,
            "crop_h": int,
            "crop_x": int,
            "crop_y": int,
            "detected": bool,
            "position": str  # 'bottom-right', 'top-left', 'bottom-left', 'top-right'
        }
    """
    logger.info("🤖 Running AI OpenCV Corner-Restricted Facecam Detector on video: %s", video_path)

    # Default fallback for Windah Basudara gaming streams (Bottom-Right or Top-Left webcam box)
    default_result = {
        "crop_w": 640,
        "crop_h": 480,
        "crop_x": 0,
        "crop_y": 0,
        "detected": False,
        "position": "top-left"
    }

    if cv2 is None or not os.path.exists(video_path):
        logger.warning("OpenCV is not installed or video file missing. Returning default facecam crop.")
        return default_result

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning("Could not open video file via OpenCV. Returning default facecam crop.")
            return default_result

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

        # Multi-Cascade Classifiers for high-accuracy face & profile detection
        cascades = []
        for c_name in ["haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"]:
            c_path = cv2.data.haarcascades + c_name
            if os.path.exists(c_path):
                cascades.append(cv2.CascadeClassifier(c_path))

        if sample_timestamps_sec is None:
            # Sample 8 frames across the video
            sample_timestamps_sec = [5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0, 75.0]

        corner_faces: List[Tuple[int, int, int, int, str]] = []
        corner_frames: List[np.ndarray] = []

        for ts in sample_timestamps_sec:
            target_frame = int(ts * fps)
            if target_frame >= total_frames:
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            corner_frames.append(frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect faces across all cascades
            for cascade in cascades:
                faces = cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(70, 70),
                    maxSize=(int(video_width * 0.45), int(video_height * 0.55))
                )
                for (fx, fy, fw, fh) in faces:
                    fc_x = fx + fw // 2
                    fc_y = fy + fh // 2

                    # 🚨 FILTER OUT CENTER GAMEPLAY NPCs:
                    # Ignore faces detected in the central 40% of gameplay screen!
                    if (0.30 * video_width < fc_x < 0.70 * video_width) and (0.25 * video_height < fc_y < 0.75 * video_height):
                        continue

                    # Classify outer corner
                    pos = "top-left"
                    if fc_x > video_width * 0.5 and fc_y > video_height * 0.5:
                        pos = "bottom-right"
                    elif fc_x < video_width * 0.5 and fc_y > video_height * 0.5:
                        pos = "bottom-left"
                    elif fc_x > video_width * 0.5 and fc_y < video_height * 0.5:
                        pos = "top-right"
                    else:
                        pos = "top-left"

                    corner_faces.append((fx, fy, fw, fh, pos))

        cap.release()

        # ── STAGE 1: Haar Cascade Corner Face Lock ───────────────────────────
        if corner_faces:
            # Count frequency of detections per corner
            pos_counts = {}
            for f in corner_faces:
                p = f[4]
                pos_counts[p] = pos_counts.get(p, 0) + 1

            best_pos = max(pos_counts, key=pos_counts.get)
            matched_faces = [f for f in corner_faces if f[4] == best_pos]

            avg_x = int(sum(f[0] for f in matched_faces) / len(matched_faces))
            avg_y = int(sum(f[1] for f in matched_faces) / len(matched_faces))
            avg_w = int(sum(f[2] for f in matched_faces) / len(matched_faces))
            avg_h = int(sum(f[3] for f in matched_faces) / len(matched_faces))

            center_x = avg_x + avg_w // 2
            center_y = avg_y + avg_h // 2

            # Generous bounding box for full webcam frame
            box_w = max(580, int(avg_w * 2.5))
            box_h = int(box_w * (960 / 1080))

            crop_x = max(0, min(video_width - box_w, center_x - box_w // 2))
            crop_y = max(0, min(video_height - box_h, center_y - box_h // 2))

            logger.info("✅ [STAGE 1] AI locked onto streamer facecam in corner '%s' at x=%d, y=%d (%dx%d)",
                        best_pos, crop_x, crop_y, box_w, box_h)

            return {
                "crop_w": box_w,
                "crop_h": box_h,
                "crop_x": crop_x,
                "crop_y": crop_y,
                "detected": True,
                "position": best_pos
            }

        # ── STAGE 2: Motion Variance Corner Analysis (Fallback) ───────────────
        if len(corner_frames) >= 2 and np is not None:
            logger.info("🔄 [STAGE 2] Running Motion Variance Corner Analysis across 4 outer corners...")
            
            # Define 4 outer corner ROIs
            w_crop = int(video_width * 0.38)
            h_crop = int(video_height * 0.48)

            rois = {
                "top-left": (0, 0, w_crop, h_crop),
                "bottom-right": (video_width - w_crop, video_height - h_crop, w_crop, h_crop),
                "bottom-left": (0, video_height - h_crop, w_crop, h_crop),
                "top-right": (video_width - w_crop, 0, w_crop, h_crop),
            }

            corner_variances = {}
            for pos_name, (rx, ry, rw, rh) in rois.items():
                crops = [cv2.cvtColor(fr[ry:ry+rh, rx:rx+rw], cv2.COLOR_BGR2GRAY) for fr in corner_frames if fr is not None]
                if len(crops) >= 2:
                    diffs = [np.mean(np.abs(crops[i].astype(float) - crops[i-1].astype(float))) for i in range(1, len(crops))]
                    corner_variances[pos_name] = float(np.mean(diffs))

            if corner_variances:
                best_corner = max(corner_variances, key=corner_variances.get)
                rx, ry, rw, rh = rois[best_corner]

                logger.info("✅ [STAGE 2] Motion Variance locked onto active webcam corner '%s' (var: %.2f) at x=%d, y=%d",
                            best_corner, corner_variances[best_corner], rx, ry)

                return {
                    "crop_w": rw,
                    "crop_h": rh,
                    "crop_x": rx,
                    "crop_y": ry,
                    "detected": True,
                    "position": best_corner
                }

    except Exception as e:
        logger.error("AI Facecam detection failed: %s. Reverting to default top-left.", str(e))

    return default_result
