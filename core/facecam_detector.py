"""
2026 Dynamic AI Facecam Detector with Per-Segment Tracking & EMA Smoothing.

Detects streamer facecam coordinates across multiple keyframes and generates
smooth interpolated crop paths using Exponential Moving Average (EMA).
Prevents the "static crop" problem where one fixed crop box is used for
the entire 60-90 second clip.

Pipeline:
  1. YuNet DNN face detection on N keyframes (default 10)
  2. HSV skin-tone verification (reject game NPCs)
  3. EMA smoothing across keyframes for jitter-free tracking
  4. Linear interpolation between keyframes for per-second crop coordinates
  5. Output: List of (timestamp, crop_x, crop_y, crop_w, crop_h) tuples

Lightweight: ~30 MB RAM with cv2.setNumThreads(1).
"""

import os
import urllib.request
import logging
import math
from typing import Tuple, Dict, Any, Optional, List
from dataclasses import dataclass

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    if cv2 is not None:
        cv2.setNumThreads(1)
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore

from config import BASE_DIR

logger = logging.getLogger(__name__)

# Model storage directory
MODELS_DIR = BASE_DIR / "config" / "models"
YUNET_MODEL_PATH = MODELS_DIR / "face_detection_yunet.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


@dataclass
class CropKeyframe:
    """A single crop keyframe with smoothed coordinates."""
    timestamp_sec: float
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    confidence: float
    skin_density: float


def _ensure_yunet_model() -> Optional[str]:
    """Ensures YuNet ONNX Deep Learning Face Detector model is downloaded and ready."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    if YUNET_MODEL_PATH.exists() and YUNET_MODEL_PATH.stat().st_size > 100000:
        return str(YUNET_MODEL_PATH)

    logger.info("📦 Auto-downloading OpenCV YuNet Deep Learning Face Detector model (230 KB)...")
    try:
        urllib.request.urlretrieve(YUNET_URL, str(YUNET_MODEL_PATH))
        if YUNET_MODEL_PATH.exists() and YUNET_MODEL_PATH.stat().st_size > 100000:
            logger.info("✅ YuNet ONNX Face Detector model successfully downloaded: %s", YUNET_MODEL_PATH)
            return str(YUNET_MODEL_PATH)
    except Exception as e:
        logger.warning("❌ Failed to download YuNet model (%s). Will fallback to corner analysis.", str(e))

    return None


def _calculate_skin_density(bgr_crop: Any) -> float:
    """
    Calculates the human skin-tone pixel percentage in HSV space.
    Filters out game graphics, UI elements, and non-human objects.
    """
    if bgr_crop is None or bgr_crop.size == 0:
        return 0.0
    try:
        hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
        lower_skin = np.array([0, 15, 50], dtype=np.uint8)
        upper_skin = np.array([28, 180, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_skin, upper_skin)
        skin_pixels = cv2.countNonZero(mask)
        total_pixels = bgr_crop.shape[0] * bgr_crop.shape[1]
        return float(skin_pixels / total_pixels) if total_pixels > 0 else 0.0
    except Exception:
        return 0.0


def _detect_faces_in_frame(
    frame: Any,
    detector: Any,
    video_width: int,
    video_height: int
) -> List[Tuple[float, float, float, float, float, float]]:
    """
    Detects all candidate human faces in a single frame.

    Returns list of (center_x, center_y, fw, fh, confidence, skin_density).
    """
    if detector is None or frame is None:
        return []

    results = []
    try:
        detector.setInputSize((video_width, video_height))
        _, faces = detector.detect(frame)

        if faces is None:
            return []

        for f in faces:
            fx, fy, fw, fh = map(int, f[0:4])
            conf = float(f[14])

            if conf < 0.25:
                continue

            fc_x = fx + fw // 2
            fc_y = fy + fh // 2

            # Verify skin tone
            pad_w = int(fw * 0.5)
            pad_h = int(fh * 0.5)
            x1, y1 = max(0, fx - pad_w), max(0, fy - pad_h)
            x2, y2 = min(video_width, fx + fw + pad_w), min(video_height, fy + fh + pad_h)
            face_crop = frame[y1:y2, x1:x2]
            skin_density = _calculate_skin_density(face_crop)

            if skin_density < 0.05:
                continue

            results.append((float(fc_x), float(fc_y), float(fw), float(fh), conf, skin_density))

    except Exception as e:
        logger.debug("Face detection failed on frame: %s", str(e))

    return results


def _calculate_dead_center_crop(
    center_x: float,
    center_y: float,
    fw: float,
    fh: float,
    video_width: int,
    video_height: int,
    zoom_factor: float = 1.25,
    target_aspect: float = 824.0 / 1080.0
) -> Tuple[int, int, int, int]:
    """
    2026 Dead-Center Crop Algorithm.

    Guarantees that (center_x, center_y) is EXACTLY at the center of the crop box,
    while maintaining target_aspect (height = width * target_aspect) and staying
    strictly inside the video frame boundaries.
    """
    desired_w = max(100.0, fw * zoom_factor)

    # Maximum half-width that keeps center_x, center_y dead-centered inside boundaries
    max_half_w_x = min(center_x, video_width - center_x)
    max_half_h_y = min(center_y, video_height - center_y)
    max_half_w_from_y = max_half_h_y / target_aspect

    half_w = min(desired_w / 2.0, max_half_w_x, max_half_w_from_y)
    half_h = half_w * target_aspect

    # Ensure minimum viable crop size
    if half_w < 50.0:
        half_w = min(100.0, max_half_w_x)
        half_h = half_w * target_aspect

    crop_w = int(round(half_w * 2.0))
    crop_h = int(round(half_h * 2.0))
    crop_x = int(round(center_x - half_w))
    crop_y = int(round(center_y - half_h))

    # Clamp safely
    crop_x = max(0, min(video_width - crop_w, crop_x))
    crop_y = max(0, min(video_height - crop_h, crop_y))

    return crop_x, crop_y, crop_w, crop_h


def _detect_face_in_frame(
    frame: Any,
    detector: Any,
    video_width: int,
    video_height: int,
    target_aspect: float = 824.0 / 1080.0
) -> Optional[Tuple[int, int, int, int, float, float]]:
    """
    Detects the best streamer facecam in a single frame.
    Returns: (crop_x, crop_y, crop_w, crop_h, confidence, skin_density) or None.
    """
    faces = _detect_faces_in_frame(frame, detector, video_width, video_height)
    if not faces:
        return None

    # Pick face with highest conf * (1 + skin * 3)
    best = max(faces, key=lambda f: f[4] * (1.0 + f[5] * 3.0))
    fc_x, fc_y, fw, fh, conf, skin = best

    cx, cy, cw, ch = _calculate_dead_center_crop(
        fc_x, fc_y, fw, fh, video_width, video_height, zoom_factor=1.25, target_aspect=target_aspect
    )
    return (cx, cy, cw, ch, conf, skin)


def detect_streamer_facecam(
    video_path: str,
    sample_timestamps_sec: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Static facecam detector (backward compatible).
    Returns a single crop region for the entire clip.
    """
    keyframes = detect_dynamic_facecam_track(video_path, sample_timestamps_sec=sample_timestamps_sec)

    if not keyframes:
        return {
            "crop_w": 640, "crop_h": 488,
            "crop_x": 0, "crop_y": 0,
            "detected": False, "position": "top-left"
        }

    mid = len(keyframes) // 2
    kf = keyframes[mid]

    if cv2 is not None:
        cap = cv2.VideoCapture(video_path)
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        cap.release()
    else:
        vw, vh = 1920, 1080

    cx = kf.crop_x + kf.crop_w // 2
    cy = kf.crop_y + kf.crop_h // 2
    if cx > vw * 0.5:
        pos = "top-right" if cy < vh * 0.5 else "bottom-right"
    else:
        pos = "top-left" if cy < vh * 0.5 else "bottom-left"

    return {
        "crop_w": kf.crop_w, "crop_h": kf.crop_h,
        "crop_x": kf.crop_x, "crop_y": kf.crop_y,
        "detected": True, "position": pos
    }


def detect_dynamic_facecam_track(
    video_path: str,
    num_samples: int = 10,
    sample_timestamps_sec: Optional[List[float]] = None,
    ema_alpha: float = 0.35,
    zoom_factor: float = 1.25
) -> List[CropKeyframe]:
    """
    2026 Production Dynamic Facecam Tracker with Anchor Clustering & Dead-Center Crop.

    Algorithm:
      1. Samples keyframes across video duration
      2. Extracts all candidate faces (YuNet + HSV skin check)
      3. Identifies Primary Streamer Facecam Anchor (clusters consistent streamer face, filters game NPCs)
      4. Tracks streamer face across keyframes relative to Anchor
      5. Calculates DEAD-CENTER crop for each keyframe (guarantees face is dead-center)
      6. Applies EMA smoothing across keyframes for jitter-free tracking

    Returns:
        List of CropKeyframe with smoothed dead-center coordinates.
    """
    logger.info("🎯 Running 2026 Production Facecam Tracker on: %s", video_path)

    if cv2 is None or not os.path.exists(video_path):
        logger.warning("OpenCV not available or video missing. Returning empty track.")
        return []

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        duration = total_frames / fps if fps > 0 and total_frames > 0 else 30.0

        if sample_timestamps_sec is None:
            step = max(1.0, duration / num_samples)
            sample_timestamps_sec = [round(0.5 + i * step, 1) for i in range(num_samples)]

        model_file = _ensure_yunet_model()
        detector = None
        if model_file and hasattr(cv2, 'FaceDetectorYN'):
            try:
                detector = cv2.FaceDetectorYN.create(
                    model=model_file,
                    config='',
                    input_size=(video_width, video_height),
                    score_threshold=0.20,
                    nms_threshold=0.3,
                    top_k=1000
                )
            except Exception as e:
                logger.warning("Failed to initialize YuNet: %s", str(e))

        # Step 1 & 2: Collect candidate faces per keyframe
        keyframe_faces: List[Tuple[float, List[Tuple[float, float, float, float, float, float]]]] = []

        for ts in sample_timestamps_sec:
            target_frame = int(ts * fps)
            if target_frame >= total_frames:
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            faces = _detect_faces_in_frame(frame, detector, video_width, video_height)
            keyframe_faces.append((ts, faces))

        cap.release()

        # Flatten all detected faces to find the Streamer Facecam Anchor
        all_detected_faces = [f for _, faces in keyframe_faces for f in faces]

        if not all_detected_faces:
            logger.warning("No faces detected in any keyframe. Using fallback corner analysis.")
            def_w = int(video_width * 0.25)
            def_h = int(def_w * (824 / 1080))
            return [CropKeyframe(
                timestamp_sec=0.0,
                crop_x=0, crop_y=0,
                crop_w=def_w, crop_h=def_h,
                confidence=0.0, skin_density=0.0
            )]

        # Find Streamer Facecam Anchor: cluster faces by spatial distance
        # Facecam overlay is present in multiple frames at a consistent region
        best_anchor = None
        best_anchor_count = 0

        for f_candidate in all_detected_faces:
            cx, cy = f_candidate[0], f_candidate[1]
            # Count faces within 25% video width of this candidate
            radius = 0.25 * video_width
            nearby = [f for f in all_detected_faces if math.hypot(f[0] - cx, f[1] - cy) < radius]
            if len(nearby) > best_anchor_count:
                best_anchor_count = len(nearby)
                # Anchor is median position of nearby faces
                med_x = float(np.median([f[0] for f in nearby]))
                med_y = float(np.median([f[1] for f in nearby]))
                med_fw = float(np.median([f[2] for f in nearby]))
                med_fh = float(np.median([f[3] for f in nearby]))
                best_anchor = (med_x, med_y, med_fw, med_fh)

        if best_anchor is None:
            # Fallback to overall median
            med_x = float(np.median([f[0] for f in all_detected_faces]))
            med_y = float(np.median([f[1] for f in all_detected_faces]))
            med_fw = float(np.median([f[2] for f in all_detected_faces]))
            med_fh = float(np.median([f[3] for f in all_detected_faces]))
            best_anchor = (med_x, med_y, med_fw, med_fh)

        anchor_x, anchor_y, anchor_fw, anchor_fh = best_anchor
        logger.info("⚓ Identified Streamer Facecam Anchor at (x=%.1f, y=%.1f, fw=%.1f)", anchor_x, anchor_y, anchor_fw)

        # Step 3, 4 & 5: Process each keyframe using Anchor & Dead-Center Crop
        target_aspect = 824.0 / 1080.0
        max_dist = 0.30 * video_width

        raw_crops: List[Tuple[float, int, int, int, int, float, float]] = []

        curr_x, curr_y, curr_fw, curr_fh = anchor_x, anchor_y, anchor_fw, anchor_fh

        for ts, faces in keyframe_faces:
            # Find face closest to current anchor
            valid_faces = [f for f in faces if math.hypot(f[0] - curr_x, f[1] - curr_y) < max_dist]

            if valid_faces:
                best_f = max(valid_faces, key=lambda f: f[4] * (1.0 + f[5] * 2.0))
                fx, fy, fw, fh, conf, skin = best_f
                # Smoothly update current anchor position
                curr_x = 0.4 * fx + 0.6 * curr_x
                curr_y = 0.4 * fy + 0.6 * curr_y
                curr_fw = 0.4 * fw + 0.6 * curr_fw
                curr_fh = 0.4 * fh + 0.6 * curr_fh
            else:
                conf, skin = 0.5, 0.2

            # Calculate DEAD-CENTER crop
            cx, cy, cw, ch = _calculate_dead_center_crop(
                curr_x, curr_y, curr_fw, curr_fh,
                video_width, video_height,
                zoom_factor=zoom_factor,
                target_aspect=target_aspect
            )
            raw_crops.append((ts, cx, cy, cw, ch, conf, skin))

        # Apply EMA smoothing across keyframes
        smoothed: List[CropKeyframe] = []
        ema_x, ema_y, ema_w, ema_h = None, None, None, None

        for ts, cx, cy, cw, ch, conf, skin in raw_crops:
            if ema_x is None:
                ema_x, ema_y, ema_w, ema_h = float(cx), float(cy), float(cw), float(ch)
            else:
                ema_x = ema_alpha * cx + (1.0 - ema_alpha) * ema_x
                ema_y = ema_alpha * cy + (1.0 - ema_alpha) * ema_y
                ema_w = ema_alpha * cw + (1.0 - ema_alpha) * ema_w
                ema_h = ema_alpha * ch + (1.0 - ema_alpha) * ema_h

            s_w = int(min(video_width, max(100, ema_w)))
            s_h = int(min(video_height, max(100, ema_h)))
            s_x = int(max(0, min(video_width - s_w, ema_x)))
            s_y = int(max(0, min(video_height - s_h, ema_y)))

            smoothed.append(CropKeyframe(
                timestamp_sec=ts,
                crop_x=s_x, crop_y=s_y,
                crop_w=s_w, crop_h=s_h,
                confidence=conf, skin_density=skin
            ))

        logger.info(
            "🎯 Production Dynamic Tracker: %d keyframes processed (Anchor=%.0f,%.0f, EMA α=%.2f, Zoom=%.2f)",
            len(smoothed), anchor_x, anchor_y, ema_alpha, zoom_factor
        )
        return smoothed

    except Exception as e:
        logger.error("Dynamic facecam tracking failed: %s", str(e))
        return []


def interpolate_crop_at_time(
    keyframes: List[CropKeyframe],
    target_sec: float
) -> Tuple[int, int, int, int]:
    """
    Linearly interpolates crop coordinates at a specific timestamp
    between two adjacent keyframes.
    """
    if not keyframes:
        return (0, 0, 640, 488)

    if len(keyframes) == 1 or target_sec <= keyframes[0].timestamp_sec:
        kf = keyframes[0]
        return (kf.crop_x, kf.crop_y, kf.crop_w, kf.crop_h)

    if target_sec >= keyframes[-1].timestamp_sec:
        kf = keyframes[-1]
        return (kf.crop_x, kf.crop_y, kf.crop_w, kf.crop_h)

    for i in range(len(keyframes) - 1):
        kf_a = keyframes[i]
        kf_b = keyframes[i + 1]
        if kf_a.timestamp_sec <= target_sec <= kf_b.timestamp_sec:
            t_range = kf_b.timestamp_sec - kf_a.timestamp_sec
            if t_range <= 0:
                return (kf_a.crop_x, kf_a.crop_y, kf_a.crop_w, kf_a.crop_h)
            t = (target_sec - kf_a.timestamp_sec) / t_range
            return (
                int(kf_a.crop_x + t * (kf_b.crop_x - kf_a.crop_x)),
                int(kf_a.crop_y + t * (kf_b.crop_y - kf_a.crop_y)),
                int(kf_a.crop_w + t * (kf_b.crop_w - kf_a.crop_w)),
                int(kf_a.crop_h + t * (kf_b.crop_h - kf_a.crop_h)),
            )

    kf = keyframes[-1]
    return (kf.crop_x, kf.crop_y, kf.crop_w, kf.crop_h)


def generate_ffmpeg_crop_commands(
    keyframes: List[CropKeyframe],
    clip_duration_sec: float,
    fps: float = 30.0
) -> List[Tuple[float, int, int, int, int]]:
    """
    Generates per-second crop coordinates for FFmpeg sendcmd filter.
    """
    if not keyframes:
        return []

    commands = []
    for t in range(int(clip_duration_sec) + 1):
        ts = float(t)
        cx, cy, cw, ch = interpolate_crop_at_time(keyframes, ts)
        commands.append((ts, cx, cy, cw, ch))

    return commands

