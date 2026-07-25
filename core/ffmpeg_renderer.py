"""
CPU-optimized 1-pass FFmpeg vertical video renderer for YouTube Shorts and TikTok.
Transforms 16:9 landscape videos into stylized 9:16 vertical shorts with blurred background
and optional burned-in animated subtitles.
"""

import os
import subprocess
import logging
from typing import Optional
from config import TARGET_WIDTH, TARGET_HEIGHT

logger = logging.getLogger(__name__)


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Gets exact (width, height) of a video file via OpenCV or ffprobe."""
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
            cap.release()
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and "x" in res.stdout:
            parts = res.stdout.strip().split("x")
            return int(parts[0]), int(parts[1])
    except Exception:
        pass

    return 1920, 1080


def render_vertical_shorts(
    input_video: str,
    start_time: float,
    duration: float,
    output_path: str,
    subtitle_path: Optional[str] = None
) -> bool:
    """
    Renders a 100% Full-Screen 9:16 Vertical Short (1080x1920).
    HARAM LETTERBOX / HARAM BLURRED BARS / HARAM WIDE SHOT!
    Uses Podcast 2-Stack Split-Screen Crop:
    - TOP HALF (1080x960): Left Speaker (Host) cropped tight & centered.
    - BOTTOM HALF (1080x960): Right Speaker (Guest) cropped tight & centered.
    - DIVIDER: Sleek glassmorphic neon cyan accent divider line between top and bottom.
    - CANVAS: 100% Filled 1080x1920 screen (Zero letterbox, Zero blurred bars).
    """
    logger.info(
        "Rendering 100% Full-Screen Podcast Split-Screen 9:16 (Start: %.2fs, Duration: %.2fs) -> %s",
        start_time, duration, output_path
    )

    if not os.path.exists(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return False

    # 1. Top Half Stream (1080x960): Left Speaker (x=0 to iw/2) cropped tight & scaled to fill 1080x960
    top_filter = "[0:v]crop=iw/2:ih:0:0,scale=w=1080:h=960:force_original_aspect_ratio=increase,crop=1080:960[top]"

    # 2. Bottom Half Stream (1080x960): Right Speaker (x=iw/2 to iw) cropped tight & scaled to fill 1080x960
    bottom_filter = "[0:v]crop=iw/2:ih:iw/2:0,scale=w=1080:h=960:force_original_aspect_ratio=increase,crop=1080:960[bottom]"

    # 3. Stack Top & Bottom Vertically (Total 1080x1920 canvas)
    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"

    # 4. Draw sleek glassmorphic neon divider accent line at center Y=956..960
    divider_filter = (
        "[stacked]drawbox=y=956:color=cyan@0.8:width=iw:height=8:t=fill,"
        "drawbox=y=958:color=white@0.9:width=iw:height=4:t=fill,fps=30[outv]"
    )

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.2f}",
        "-t", f"{duration:.2f}",
        "-i", input_video,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "22",
        "-threads", "0",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    logger.info("Executing 100% Full-Screen 9:16 Split-Screen FFmpeg superfast render command...")

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=300
        )
        logger.info("FFmpeg 100% Full-Screen render completed successfully: %s", output_path)
        return True
    except subprocess.TimeoutExpired as te:
        raise RuntimeError(f"FFmpeg Podcast Split-Screen render timed out after 300s: {output_path}") from te
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr[-800:] if e.stderr else str(e)
        raise RuntimeError(f"FFmpeg Podcast Split-Screen render failed: {err_msg}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error during Podcast Split-Screen render: {str(e)}") from e




def render_gaming_split_shorts(
    input_video: str,
    start_time: float,
    duration: float,
    output_path: str,
    facecam_coords: Optional[dict] = None,
    subtitle_path: Optional[str] = None
) -> bool:
    """
    Renders a 9:16 Gaming Short with 2-Stack Split Screen (Windah Basudara / Wayin AI Killer):
    - TOP HALF (1080x960): Streamer's facecam dynamically cropped from facecam_coords.
    - BOTTOM HALF (1080x960): Main gameplay stream centered crop.
    - DIVIDER: Modern glassmorphic neon divider accent between top and bottom half.
    - SUBTITLES: CapCut Word-by-Word Active Highlighting positioned over gameplay section.
    """
    logger.info(
        "Rendering Gaming Split-Screen 9:16 (Start: %.2fs, Duration: %.2fs) -> %s",
        start_time, duration, output_path
    )

    if not os.path.exists(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return False

    # Probe input video dimensions to guarantee 100% boundary-safe FFmpeg crop parameters
    in_w, in_h = _get_video_dimensions(input_video)

    # Default facecam crop coordinates if not provided (Top-Left crop for Windah Basudara facecam)
    fc = facecam_coords or {"crop_w": 640, "crop_h": 480, "crop_x": 0, "crop_y": 0}
    raw_cw = max(100, int(fc.get("crop_w", 640)))
    raw_ch = max(100, int(fc.get("crop_h", 480)))
    raw_cx = max(0, int(fc.get("crop_x", 0)))
    raw_cy = max(0, int(fc.get("crop_y", 0)))

    # Clamp crop dimensions to input video boundaries (w <= in_w, h <= in_h, x+w <= in_w, y+h <= in_h)
    cw = min(in_w, raw_cw)
    ch = min(in_h, raw_ch)
    cx = max(0, min(in_w - cw, raw_cx))
    cy = max(0, min(in_h - ch, raw_cy))

    logger.info("Clamped Facecam Crop for Video (%dx%d): crop=%d:%d:%d:%d", in_w, in_h, cw, ch, cx, cy)

    # 1. TOP HALF (1080x960): Streamer Facecam cropped & scaled to fill 1080x960
    top_filter = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=w=1080:h=960:force_original_aspect_ratio=increase,crop=1080:960[top]"

    # 2. BOTTOM HALF (1080x960): Main Gameplay Stream centered crop & scaled to fill 1080x960
    bottom_filter = "[0:v]scale=w=1080:h=960:force_original_aspect_ratio=increase,crop=1080:960[bottom]"

    # 3. Stack Top & Bottom Vertically (Total 1080x1920)
    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"

    # 4. Draw sleek glassmorphic neon divider line across the center (Y=960)
    divider_filter = (
        "[stacked]drawbox=y=956:color=cyan@0.8:width=iw:height=8:t=fill,"
        "drawbox=y=958:color=white@0.9:width=iw:height=4:t=fill[base]"
    )

    # 5. Burn-in Subtitles on center divider boundary if provided
    if subtitle_path and os.path.exists(subtitle_path):
        escaped_sub_path = _escape_ffmpeg_path(subtitle_path)
        if subtitle_path.endswith(".ass"):
            final_sub_filter = f"[base]ass='{escaped_sub_path}'[outv]"
        else:
            sub_style = "Fontsize=28,PrimaryColour=&H0066FF00&,OutlineColour=&H000000&,Bold=1,Italic=1,Alignment=2,MarginV=900"
            final_sub_filter = f"[base]subtitles='{escaped_sub_path}':force_style='{sub_style}'[outv]"
    else:
        final_sub_filter = "[base]fps=30[outv]"

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}; {final_sub_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.2f}",
        "-t", f"{duration:.2f}",
        "-i", input_video,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "17",
        "-b:v", "8M",
        "-maxrate", "10M",
        "-bufsize", "16M",
        "-threads", "0",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    logger.info("Executing Gaming Split-Screen (Top: Facecam, Bottom: Gameplay) 1080p Full HD render command...")
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=300
        )
        logger.info("Gaming Split-Screen render completed successfully: %s", output_path)
        return True
    except subprocess.TimeoutExpired as te:
        raise RuntimeError(f"FFmpeg Gaming Split-Screen render timed out after 300s: {output_path}") from te
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr[-600:] if e.stderr else str(e)
        logger.warning("Gaming Split-Screen primary render failed (%s). Retrying fallback without subtitles...", err_msg)
        filter_complex_fallback = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}".replace("[base]", "[outv]")
        fallback_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.2f}",
            "-t", f"{duration:.2f}",
            "-i", input_video,
            "-filter_complex", filter_complex_fallback,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "17",
            "-b:v", "8M",
            "-maxrate", "10M",
            "-bufsize", "16M",
            "-threads", "0",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]

        try:
            subprocess.run(
                fallback_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=300
            )
            logger.info("Fallback Gaming Split-Screen render completed successfully: %s", output_path)
            return True
        except subprocess.CalledProcessError as fallback_err:
            fallback_msg = fallback_err.stderr[-800:] if fallback_err.stderr else str(fallback_err)
            raise RuntimeError(f"FFmpeg Gaming Split-Screen render failed: {fallback_msg}") from fallback_err
        except Exception as fb_ex:
            raise RuntimeError(f"Fallback Gaming Split-Screen error: {str(fb_ex)}") from fb_ex
    except Exception as e:
        raise RuntimeError(f"Unexpected error during Gaming Split-Screen render: {str(e)}") from e






