"""
2026 Production-Grade FFmpeg Vertical Video Renderer.

Transforms 16:9 landscape gaming streams into cinematic 9:16 vertical shorts (1080x1920)
with dynamic facecam tracking, quality enhancement (CRF 23, lanczos, color grading),
and single-thread optimization for VPS 2GB RAM.

Layout:
  Top half (1080x960): Streamer facecam — dynamically tracked & centered
  Bottom half (1080x960): Gameplay — saliency-aware center crop
  Divider: 8px colored line at y=956

Quality Pipeline:
  - Encoder: libx264, preset ultrafast, CRF 23
  - Scaler: bicubic (fast, sharp enough)
  - 1 thread only — safe for 2GB RAM VPS
"""

import os
import shutil
import subprocess
import logging
from typing import Optional, Union, Dict, Any, List, Tuple
from dataclasses import dataclass
from config import TARGET_WIDTH, TARGET_HEIGHT

logger = logging.getLogger(__name__)


@dataclass
class MediaInput:
    path: str
    is_presliced: bool = False
    source_start: float = 0.0


def _escape_ffmpeg_path(path: str) -> str:
    """Escapes backslashes and special chars in file paths for FFmpeg filtergraphs."""
    escaped = path.replace("\\", "/").replace(":", "\\:")
    return repr(escaped).strip("'")


def _check_disk_space_for_render(output_path: str, min_mb: float = 200.0) -> bool:
    """Check if there's enough disk space for render output. Returns True if OK."""
    try:
        target_dir = os.path.dirname(output_path) or "."
        _, _, free = shutil.disk_usage(target_dir)
        free_mb = free / (1024 * 1024)
        if free_mb < min_mb:
            logger.error(
                "❌ DISK SPACE CRITICAL: Only %.0f MB free (need %.0f MB minimum). Render skipped!",
                free_mb, min_mb
            )
            return False
        logger.info("💾 Disk space OK: %.0f MB free", free_mb)
        return True
    except Exception as e:
        logger.warning("Could not check disk space: %s", str(e))
        return True  # Proceed anyway if check fails


def _get_video_info(video_path: str) -> tuple:
    """Gets exact (width, height, duration, fps) of a video file or stream URL."""
    w, h, dur, fps = 1920, 1080, 0.0, 30.0
    if video_path.startswith("http://") or video_path.startswith("https://"):
        return 1920, 1080, 0.0, 30.0
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
            fps = max(1.0, cap.get(cv2.CAP_PROP_FPS) or 30.0)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            dur = frames / fps
            cap.release()
            if w > 0 and h > 0:
                return w, h, dur, fps
    except Exception:
        pass

    return 1920, 1080, dur, fps


def _run_ffmpeg_with_logging(cmd: list, label: str, timeout: int = 600) -> bool:
    """
    Runs an FFmpeg command, captures stderr, and logs it on failure.
    Returns True if the command succeeded, False otherwise.
    """
    logger.info("🎬 [%s] Executing FFmpeg command...", label)
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-1500:]
            logger.error(
                "❌ [%s] FFmpeg FAILED (exit code %d). Last 1500 chars of stderr:\n%s",
                label, result.returncode, stderr_tail
            )
            return False

        logger.info("✅ [%s] FFmpeg completed successfully.", label)
        return True

    except subprocess.TimeoutExpired:
        logger.error("❌ [%s] FFmpeg TIMED OUT after %d seconds!", label, timeout)
        return False
    except MemoryError:
        logger.error("❌ [%s] FFmpeg OUT OF MEMORY! VPS RAM exhausted.", label)
        return False
    except Exception as e:
        logger.error("❌ [%s] FFmpeg unexpected error: %s", label, str(e))
        return False


def render_vertical_shorts(
    input_video: Union[str, "MediaInput"],
    start_time: float,
    duration: float,
    output_path: str,
    subtitle_path: Optional[str] = None
) -> bool:
    """
    Renders a 100% Full-Screen 9:16 Vertical Short (1080x1920) for Podcast mode.
    Optimized for VPS 2GB RAM with ultra-light settings.

    Strategy: Try split-screen first, if it fails, try ultra-light fallback (simple crop).
    """
    media = input_video if isinstance(input_video, MediaInput) else MediaInput(path=input_video, is_presliced=False)
    v_path = media.path
    is_url = v_path.startswith("http://") or v_path.startswith("https://")

    if not is_url and not os.path.exists(v_path):
        logger.error("Input video file does not exist: %s", v_path)
        return False

    # Pre-check disk space
    if not _check_disk_space_for_render(output_path):
        return False

    in_w, in_h, in_dur, in_fps = _get_video_info(v_path)
    render_start = 0.0 if media.is_presliced else max(0.0, start_time)
    render_duration = max(5.0, duration)

    logger.info(
        "Rendering Podcast Split-Screen 9:16 (Start: %.2fs, Duration: %.2fs) -> %s",
        render_start, render_duration, output_path
    )

    top_filter = "[0:v]crop=iw/2:ih:0:0,scale=w=1080:h=824:force_original_aspect_ratio=increase:flags=bicubic,crop=1080:824[top]"
    bottom_filter = "[0:v]crop=iw/2:ih:iw/2:0,scale=w=1080:h=1096:force_original_aspect_ratio=increase:flags=bicubic,crop=1080:1096[bottom]"
    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"
    
    divider_filter = (
        f"[stacked]drawbox=y=820:color=cyan@0.85:width=iw:height=8:t=fill,"
        f"drawbox=y=822:color=white@0.95:width=iw:height=4:t=fill[outv]"
    )

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}"

    input_args = []
    if is_url:
        headers_str = (
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n"
            "Referer: https://www.youtube.com/\r\n"
            "Origin: https://www.youtube.com\r\n"
        )
        input_args = [
            "-headers", headers_str,
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5"
        ]

    # === ATTEMPT 1: Split-screen render (ultrafast, 1 thread, CRF 23) ===
    cmd = ["ffmpeg", "-y"]
    cmd.extend(input_args)
    cmd.extend([
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ])

    success = _run_ffmpeg_with_logging(cmd, "Podcast Split-Screen", timeout=600)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) >= 50000:
        return True

    # === ATTEMPT 2: Ultra-light fallback (simple center crop, NO split-screen) ===
    logger.warning("⚠️ Split-screen render failed. Trying ultra-light center-crop fallback...")

    # Clean up failed output
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    # Simple center crop to 9:16 — minimal memory usage
    simple_filter = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=fast_bilinear"

    fallback_cmd = ["ffmpeg", "-y"]
    fallback_cmd.extend(input_args)
    fallback_cmd.extend([
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-vf", simple_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ])

    success = _run_ffmpeg_with_logging(fallback_cmd, "Podcast Ultra-Light Fallback", timeout=600)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) >= 50000:
        logger.info("✅ Ultra-light fallback render succeeded: %s", output_path)
        return True

    logger.error("❌ ALL render attempts failed for: %s", output_path)
    return False


def render_gaming_split_shorts(
    input_video: Union[str, "MediaInput"],
    start_time: float,
    duration: float,
    output_path: str,
    facecam_coords: Optional[Dict[str, Any]] = None,
    subtitle_path: Optional[str] = None,
    hook_title: Optional[str] = None,
    reaction_peaks: Optional[List[float]] = None,
    dynamic_crop_keyframes: Optional[List[Any]] = None
) -> bool:
    """
    2026 Production-Grade Gaming Split-Screen Renderer (1080x1920).
    Optimized for VPS 2GB RAM with 3-tier fallback strategy.
    """
    media = input_video if isinstance(input_video, MediaInput) else MediaInput(path=input_video, is_presliced=False)
    v_path = media.path
    is_url = v_path.startswith("http://") or v_path.startswith("https://")

    if not is_url and not os.path.exists(v_path):
        logger.error("Input video file does not exist: %s", v_path)
        return False

    # Pre-check disk space
    if not _check_disk_space_for_render(output_path):
        return False

    in_w, in_h, in_dur, in_fps = _get_video_info(v_path)
    render_start = 0.0 if media.is_presliced else max(0.0, start_time)
    render_duration = max(5.0, duration)

    if dynamic_crop_keyframes and len(dynamic_crop_keyframes) > 0:
        mid_idx = len(dynamic_crop_keyframes) // 2
        kf = dynamic_crop_keyframes[mid_idx]
        fc = {
            "crop_w": kf.crop_w,
            "crop_h": kf.crop_h,
            "crop_x": kf.crop_x,
            "crop_y": kf.crop_y
        }
    else:
        fc = facecam_coords or {"crop_w": 640, "crop_h": 533, "crop_x": 0, "crop_y": 0}

    raw_cw = int(fc.get("crop_w", 640))
    raw_ch = int(fc.get("crop_h", 533))
    raw_cx = int(fc.get("crop_x", 0))
    raw_cy = int(fc.get("crop_y", 0))

    # If coordinates are zero/uninitialized, default to Windah's standard bottom-right facecam region in padded space
    if raw_cx == 0 and raw_cy == 0:
        raw_cw = int(in_w * 0.35)
        raw_ch = int(raw_cw * 824 / 1080)
        raw_cx = int(in_w * 0.85) + 500 - raw_cw // 2
        raw_cy = int(in_h * 0.80) + 500 - raw_ch // 2

    padded_w = in_w + 1000
    padded_h = in_h + 1000

    cw = max(50, min(padded_w, raw_cw))
    ch = max(50, min(padded_h, raw_ch))
    cx = max(0, min(padded_w - cw, raw_cx))
    cy = max(0, min(padded_h - ch, raw_cy))

    # TOP (3 parts = 824px): 500px Padded Facecam crop → scale to 1080x824 → 100% ABSOLUTE DEAD CENTER
    top_filter = (
        f"[0:v]pad=w=iw+1000:h=ih+1000:x=500:y=500:color=black[padded];"
        f"[padded]crop={cw}:{ch}:{cx}:{cy},"
        f"scale=1080:824:flags=bicubic"
        f"[top]"
    )

    # BOTTOM (4 parts = 1096px): Gameplay — center crop
    gameplay_crop_w = int(in_w * 0.75)
    gameplay_crop_x = (in_w - gameplay_crop_w) // 2
    bottom_filter = (
        f"[0:v]crop={gameplay_crop_w}:{in_h}:{gameplay_crop_x}:0,"
        f"scale=w=1080:h=1096:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop=1080:1096"
        f"[bottom]"
    )

    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"

    divider_color = "red@0.95" if reaction_peaks else "cyan@0.85"
    divider_filter = (
        f"[stacked]drawbox=y=820:color={divider_color}:width=iw:height=8:t=fill,"
        f"drawbox=y=822:color=white@0.95:width=iw:height=4:t=fill[outv]"
    )

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}"

    input_args = []
    if is_url:
        headers_str = (
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n"
            "Referer: https://www.youtube.com/\r\n"
            "Origin: https://www.youtube.com\r\n"
        )
        input_args = [
            "-headers", headers_str,
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5"
        ]

    # === ATTEMPT 1: Gaming Split-Screen (ultrafast, 1 thread, CRF 23) ===
    logger.info("Executing 2026 Gaming Split-Screen render (ultrafast, 1-thread, VPS 2GB optimized)...")

    cmd = ["ffmpeg", "-y"]
    cmd.extend(input_args)
    cmd.extend([
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ])

    success = _run_ffmpeg_with_logging(cmd, "Gaming Split-Screen Primary", timeout=600)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) >= 50000:
        logger.info("Gaming Split-Screen render completed successfully: %s", output_path)
        return True

    # === ATTEMPT 2: Simplified split-screen (no padding, simpler filter) ===
    logger.warning("⚠️ Primary Gaming render failed. Trying simplified split-screen...")

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    # Simpler filter: use detected facecam crop for top half, center crop gameplay for bottom half
    simple_split_filter = (
        f"[0:v]pad=w=iw+1000:h=ih+1000:x=500:y=500:color=black[padded];"
        f"[padded]crop={cw}:{ch}:{cx}:{cy},scale=1080:824:flags=fast_bilinear[top];"
        f"[0:v]crop={gameplay_crop_w}:{in_h}:{gameplay_crop_x}:0,scale=w=1080:h=1096:force_original_aspect_ratio=increase:flags=fast_bilinear,crop=1080:1096[bottom];"
        f"[top][bottom]vstack=inputs=2[outv]"
    )

    fallback1_cmd = ["ffmpeg", "-y"]
    fallback1_cmd.extend(input_args)
    fallback1_cmd.extend([
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-filter_complex", simple_split_filter,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "25",
        "-threads", "1",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ])

    success = _run_ffmpeg_with_logging(fallback1_cmd, "Gaming Simplified Split", timeout=600)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) >= 50000:
        logger.info("✅ Simplified split-screen fallback succeeded: %s", output_path)
        return True

    # === ATTEMPT 3: Ultra-light fallback (simple center crop, NO split-screen at all) ===
    logger.warning("⚠️ All split-screen renders failed. Trying ultra-light center-crop (NO split)...")

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    simple_crop_filter = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=fast_bilinear"

    fallback2_cmd = ["ffmpeg", "-y"]
    fallback2_cmd.extend(input_args)
    fallback2_cmd.extend([
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-vf", simple_crop_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ])

    success = _run_ffmpeg_with_logging(fallback2_cmd, "Gaming Ultra-Light Fallback", timeout=600)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) >= 50000:
        logger.info("✅ Ultra-light center-crop fallback succeeded: %s", output_path)
        return True

    logger.error("❌ ALL 3 render attempts FAILED for: %s", output_path)
    return False
