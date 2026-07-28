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


def _detect_face_in_frame(
    frame: Any,
    detector: Any,
    video_width: int,
    video_height: int,
    target_aspect: float = 960.0 / 1080.0
) -> Optional[Tuple[int, int, int, int, float, float]]:
    """
    Detects the best streamer facecam in a single frame.

    Returns: (crop_x, crop_y, crop_w, crop_h, confidence, skin_density) or None.
    """
    if detector is None or frame is None:
        return None

    try:
        detector.setInputSize((video_width, video_height))
        _, faces = detector.detect(frame)

        if faces is None:
            return None

        best_face = None
        best_score = -1.0

        for f in faces:
            fx, fy, fw, fh = map(int, f[0:4])
            conf = float(f[14])

            fc_x = fx + fw // 2
            fc_y = fy + fh // 2

            # Filter out faces in the center game area (streamer facecam is in corners)
            in_center_x = 0.28 * video_width < fc_x < 0.72 * video_width
            in_center_y = 0.28 * video_height < fc_y < 0.72 * video_height
            if in_center_x and in_center_y:
                continue

            # Verify skin tone
            pad_w = int(fw * 0.5)
            pad_h = int(fh * 0.5)
            x1, y1 = max(0, fx - pad_w), max(0, fy - pad_h)
            x2, y2 = min(video_width, fx + fw + pad_w), min(video_height, fy + fh + pad_h)
            face_crop = frame[y1:y2, x1:x2]
            skin_density = _calculate_skin_density(face_crop)

            if skin_density < 0.06:
                continue

            # Score: confidence * (1 + skin_density * 3)
            score = conf * (1.0 + skin_density * 3.0)
            if score > best_score:
                best_score = score
                best_face = (fx, fy, fw, fh, conf, skin_density)

        if best_face is None:
            return None

        fx, fy, fw, fh, conf, skin = best_face
        center_x = fx + fw // 2
        center_y = fy + fh // 2

        # Calculate crop box with 1080:960 aspect ratio centered on face
        box_w = min(video_width, max(540, int(fw * 2.5)))
        box_h = int(box_w * target_aspect)

        crop_x = max(0, min(video_width - box_w, center_x - box_w // 2))
        crop_y = max(0, min(video_height - box_h, center_y - box_h // 2))

        return (crop_x, crop_y, box_w, box_h, conf, skin)

    except Exception as e:
        logger.debug("Face detection failed on frame: %s", str(e))
        return None


def detect_streamer_facecam(
    video_path: str,
    sample_timestamps_sec: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Static facecam detector (backward compatible).
    Returns a single crop region for the entire clip.
    Uses the dynamic tracker internally and returns the median position.
    """
    keyframes = detect_dynamic_facecam_track(video_path, sample_timestamps_sec=sample_timestamps_sec)

    if not keyframes:
        # Fallback default
        return {
            "crop_w": 640, "crop_h": 533,
            "crop_x": 0, "crop_y": 0,
            "detected": False, "position": "top-left"
        }

    # Use median keyframe as the static position
    mid = len(keyframes) // 2
    kf = keyframes[mid]

    # Determine corner position
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
    ema_alpha: float = 0.35
) -> List[CropKeyframe]:
    """
    2026 Dynamic Facecam Tracker with EMA Smoothing.

    Detects facecam position across N keyframes and applies Exponential Moving
    Average smoothing for jitter-free tracking.

    Args:
        video_path: Path to the input video.
        num_samples: Number of keyframes to sample (default 10).
        sample_timestamps_sec: Explicit timestamps to sample (overrides num_samples).
        ema_alpha: EMA smoothing factor (0.0 = max smooth, 1.0 = no smooth).

    Returns:
        List of CropKeyframe with smoothed coordinates.
    """
    logger.info("🎯 Running Dynamic Facecam Tracker on: %s", video_path)

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

        # Generate sample timestamps
        if sample_timestamps_sec is None:
            step = max(1.0, duration / num_samples)
            sample_timestamps_sec = [round(0.5 + i * step, 1) for i in range(num_samples)]

        # Initialize YuNet detector
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

        # Detect face in each keyframe
        raw_detections: List[Tuple[float, int, int, int, int, float, float]] = []

        for ts in sample_timestamps_sec:
            target_frame = int(ts * fps)
            if target_frame >= total_frames:
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            result = _detect_face_in_frame(frame, detector, video_width, video_height)
            if result:
                cx, cy, cw, ch, conf, skin = result
                raw_detections.append((ts, cx, cy, cw, ch, conf, skin))

        cap.release()

        if not raw_detections:
            logger.warning("No faces detected in any keyframe. Using fallback corner analysis.")
            # Fallback: top-left corner crop
            def_w = int(video_width * 0.38)
            def_h = int(def_w * (960 / 1080))
            return [CropKeyframe(
                timestamp_sec=0.0,
                crop_x=0, crop_y=0,
                crop_w=def_w, crop_h=def_h,
                confidence=0.0, skin_density=0.0
            )]

        # Apply EMA smoothing
        smoothed: List[CropKeyframe] = []
        ema_x, ema_y, ema_w, ema_h = None, None, None, None

        for ts, cx, cy, cw, ch, conf, skin in raw_detections:
            if ema_x is None:
                ema_x, ema_y, ema_w, ema_h = float(cx), float(cy), float(cw), float(ch)
            else:
                ema_x = ema_alpha * cx + (1 - ema_alpha) * ema_x
                ema_y = ema_alpha * cy + (1 - ema_alpha) * ema_y
                ema_w = ema_alpha * cw + (1 - ema_alpha) * ema_w
                ema_h = ema_alpha * ch + (1 - ema_alpha) * ema_h

            # Clamp to video bounds
            s_w = int(min(video_width, max(200, ema_w)))
            s_h = int(min(video_height, max(200, ema_h)))
            s_x = int(max(0, min(video_width - s_w, ema_x)))
            s_y = int(max(0, min(video_height - s_h, ema_y)))

            smoothed.append(CropKeyframe(
                timestamp_sec=ts,
                crop_x=s_x, crop_y=s_y,
                crop_w=s_w, crop_h=s_h,
                confidence=conf, skin_density=skin
            ))

        logger.info(
            "🎯 Dynamic Facecam Tracker: %d/%d keyframes tracked (EMA α=%.2f)",
            len(smoothed), len(sample_timestamps_sec), ema_alpha
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

    Args:
        keyframes: List of CropKeyframe sorted by timestamp.
        target_sec: Target timestamp to interpolate.

    Returns:
        (crop_x, crop_y, crop_w, crop_h) at the target timestamp.
    """
    if not keyframes:
        return (0, 0, 640, 533)

    if len(keyframes) == 1 or target_sec <= keyframes[0].timestamp_sec:
        kf = keyframes[0]
        return (kf.crop_x, kf.crop_y, kf.crop_w, kf.crop_h)

    if target_sec >= keyframes[-1].timestamp_sec:
        kf = keyframes[-1]
        return (kf.crop_x, kf.crop_y, kf.crop_w, kf.crop_h)

    # Find bracketing keyframes
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

    Returns list of (timestamp_sec, crop_x, crop_y, crop_w, crop_h) tuples,
    one per second of the clip duration.
    """
    if not keyframes:
        return []

    commands = []
    for t in range(int(clip_duration_sec) + 1):
        ts = float(t)
        cx, cy, cw, ch = interpolate_crop_at_time(keyframes, ts)
        commands.append((ts, cx, cy, cw, ch))

    return commands
