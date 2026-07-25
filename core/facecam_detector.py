"""
AI Facecam Detector module using OpenCV.
Detects streamer facecam coordinates (x, y, w, h) in 16:9 gaming streams (Windah Basudara style)
to dynamically crop the facecam for the Top Half (1080x960) of vertical 9:16 Shorts.
"""

import os
import logging
from typing import Tuple, Dict, Any, Optional

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore

logger = logging.getLogger(__name__)


def detect_streamer_facecam(
    video_path: str,
    sample_timestamps_sec: Optional[list[float]] = None
) -> Dict[str, Any]:
    """
    Analyzes sample frames from a gaming live stream video file to locate the streamer's facecam box.
    
    Returns:
        Dict containing crop parameters:
        {
            "crop_w": int,
            "crop_h": int,
            "crop_x": int,
            "crop_y": int,
            "detected": bool,
            "position": str  # 'top-left', 'top-right', 'bottom-left', etc.
        }
    """
    logger.info("Running AI OpenCV Facecam Detector on video: %s", video_path)

    # Default fallback for Indonesian gaming streamers (Windah Basudara / Bottom-Left facecam)
    default_result = {
        "crop_w": 640,
        "crop_h": 480,
        "crop_x": 0,
        "crop_y": 540,
        "detected": False,
        "position": "bottom-left"
    }

    if cv2 is None or not os.path.exists(video_path):
        logger.warning("OpenCV is not installed or video file missing. Returning default bottom-left facecam crop.")
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
            # Sample 8 frames across the first 60 seconds
            sample_timestamps_sec = [3.0, 8.0, 15.0, 25.0, 35.0, 45.0, 55.0]

        detected_faces = []

        for ts in sample_timestamps_sec:
            target_frame = int(ts * fps)
            if target_frame >= total_frames:
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect faces across all cascades
            for cascade in cascades:
                faces = cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(50, 50),
                    maxSize=(int(video_width * 0.45), int(video_height * 0.55))
                )
                for (fx, fy, fw, fh) in faces:
                    detected_faces.append((fx, fy, fw, fh))

        cap.release()

        if detected_faces:
            # Aggregate detected faces to find consensus facecam bounding box
            avg_x = int(sum(f[0] for f in detected_faces) / len(detected_faces))
            avg_y = int(sum(f[1] for f in detected_faces) / len(detected_faces))
            avg_w = int(sum(f[2] for f in detected_faces) / len(detected_faces))
            avg_h = int(sum(f[3] for f in detected_faces) / len(detected_faces))

            # Expand bounding box around face (padding for head & webcam frame)
            pad_w = int(avg_w * 1.8)
            pad_h = int(avg_h * 2.0)

            center_x = avg_x + avg_w // 2
            center_y = avg_y + avg_h // 2

            # Maintain 1080:960 aspect ratio (w:h = 9:8) for top half
            box_w = max(480, pad_w)
            box_h = int(box_w * (960 / 1080))

            crop_x = max(0, min(video_width - box_w, center_x - box_w // 2))
            crop_y = max(0, min(video_height - box_h, center_y - box_h // 2))

            pos = "bottom-left"
            if center_x > video_width / 2 and center_y < video_height / 2:
                pos = "top-right"
            elif center_x < video_width / 2 and center_y < video_height / 2:
                pos = "top-left"
            elif center_x > video_width / 2 and center_y > video_height / 2:
                pos = "bottom-right"

            logger.info("AI Smart Facecam Detector locked onto streamer face at x=%d, y=%d (box: %dx%d, pos: %s)",
                        crop_x, crop_y, box_w, box_h, pos)

            return {
                "crop_w": box_w,
                "crop_h": box_h,
                "crop_x": crop_x,
                "crop_y": crop_y,
                "detected": True,
                "position": pos
            }

    except Exception as e:
        logger.error("AI Facecam detection failed: %s. Falling back to default bottom-left.", str(e))

    # Smart fallback for Windah Basudara: Bottom-Left facecam box (x=0, y=540, w=640, h=480)
    return {
        "crop_w": int(video_width * 0.35) if 'video_width' in locals() else 640,
        "crop_h": int(video_height * 0.45) if 'video_height' in locals() else 480,
        "crop_x": 0,
        "crop_y": int(video_height * 0.55) if 'video_height' in locals() else 540,
        "detected": False,
        "position": "bottom-left"
    }

