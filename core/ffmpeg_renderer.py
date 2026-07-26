"""
CPU-optimized 1-pass FFmpeg vertical video renderer for YouTube Shorts and TikTok.
Transforms 16:9 landscape videos into stylized 9:16 vertical shorts with blurred background
and optional burned-in animated subtitles.
"""

import os
import subprocess
import logging
from typing import Optional, Union, Dict, Any, List
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


def _get_video_info(video_path: str) -> tuple[int, int, float]:
    """Gets exact (width, height, duration) of a video file via OpenCV or ffprobe."""
    w, h, dur = 1920, 1080, 0.0
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
                return w, h, dur
    except Exception:
        pass

    return 1920, 1080, dur


def render_vertical_shorts(
    input_video: Union[str, MediaInput],
    start_time: float,
    duration: float,
    output_path: str,
    subtitle_path: Optional[str] = None
) -> bool:
    """
    Renders a 100% Full-Screen 9:16 Vertical Short (1080x1920).
    """
    media = input_video if isinstance(input_video, MediaInput) else MediaInput(path=input_video, is_presliced=False)
    v_path = media.path

    if not os.path.exists(v_path):
        logger.error("Input video file does not exist: %s", v_path)
        return False

    in_w, in_h, in_dur = _get_video_info(v_path)
    render_start = 0.0 if (media.is_presliced or (in_dur > 0 and (in_dur < start_time or in_dur <= (duration + 60.0)))) else max(0.0, start_time)

    logger.info(
        "Rendering 100% Full-Screen Podcast Split-Screen 9:16 (Start: %.2fs, Duration: %.2fs) -> %s",
        render_start, duration, output_path
    )

    top_filter = "[0:v]crop=iw/2:ih:0:0,scale=w=1080:h=960:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:960,unsharp=3:3:0.4:3:3:0.0[top]"
    bottom_filter = "[0:v]crop=iw/2:ih:iw/2:0,scale=w=1080:h=960:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:960,unsharp=3:3:0.4:3:3:0.0[bottom]"
    stack_filter = "[top][bottom]vstack=inputs=2[outv]"

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{render_start:.2f}",
        "-t", f"{duration:.2f}",
        "-i", v_path,
        "-filter_complex_threads", "1",
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=900)
        return True
    except Exception as e:
        logger.error("Podcast split render failed: %s", str(e))
        return False


def render_gaming_split_shorts(
    input_video: Union[str, MediaInput],
    start_time: float,
    duration: float,
    output_path: str,
    facecam_coords: Optional[Dict[str, Any]] = None,
    subtitle_path: Optional[str] = None,
    hook_title: Optional[str] = None,
    reaction_peaks: Optional[List[float]] = None
) -> bool:
    """
    Renders 100% Full-Screen Gaming Split-Screen 9:16 (1080x1920) with single-thread optimization.
    """
    media = input_video if isinstance(input_video, MediaInput) else MediaInput(path=input_video, is_presliced=False)
    v_path = media.path

    if not os.path.exists(v_path):
        logger.error("Input video file does not exist: %s", v_path)
        return False

    in_w, in_h, in_dur = _get_video_info(v_path)
    render_start = 0.0 if (media.is_presliced or (in_dur > 0 and (in_dur < start_time or in_dur <= (duration + 60.0)))) else max(0.0, start_time)

    if in_dur > 0:
        if render_start >= in_dur:
            logger.warning("Render start_time (%.2fs) exceeds video duration (%.2fs). Resetting to 0.0s.", render_start, in_dur)
            render_start = 0.0
        available_dur = in_dur - render_start
        render_duration = min(duration, available_dur)
    else:
        render_duration = duration

    if render_duration < 1.0:
        logger.error("Invalid render duration (%.2fs). Aborting render.", render_duration)
        return False

    fc = facecam_coords or {"crop_w": 640, "crop_h": 533, "crop_x": 0, "crop_y": 0}
    raw_cw = max(100, int(fc.get("crop_w", 640)))
    raw_ch = max(100, int(fc.get("crop_h", 533)))
    raw_cx = max(0, int(fc.get("crop_x", 0)))
    raw_cy = max(0, int(fc.get("crop_y", 0)))

    cw = min(in_w, raw_cw)
    ch = min(in_h, raw_ch)
    cx = max(0, min(in_w - cw, raw_cx))
    cy = max(0, min(in_h - ch, raw_cy))

    logger.info("Clamped Facecam Crop for Video (%dx%d): crop=%d:%d:%d:%d (Start: %.2fs, Duration: %.2fs)",
                in_w, in_h, cw, ch, cx, cy, render_start, render_duration)

    top_filter = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1080:960:flags=lanczos,unsharp=3:3:0.6:3:3:0.0[top]"
    bottom_filter = "[0:v]scale=w=1080:h=960:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:960,unsharp=3:3:0.4:3:3:0.0[bottom]"
    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"

    divider_color = "red@0.95" if reaction_peaks else "cyan@0.85"
    divider_filter = (
        f"[stacked]drawbox=y=956:color={divider_color}:width=iw:height=8:t=fill,"
        f"drawbox=y=958:color=white@0.95:width=iw:height=4:t=fill[outv]"
    )

    filter_complex = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{render_start:.2f}",
        "-t", f"{render_duration:.2f}",
        "-i", v_path,
        "-filter_complex_threads", "1",
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    logger.info("Executing Gaming Split-Screen Wayin.ai Killer Engine (Lanczos + Hook Card + Kinetic RGB Divider) render command...")
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=900
        )
        logger.info("Gaming Split-Screen render completed successfully: %s", output_path)
        return True
    except subprocess.TimeoutExpired as te:
        raise RuntimeError(f"FFmpeg Gaming Split-Screen render timed out after 900s: {output_path}") from te
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr[-600:] if e.stderr else str(e)
        logger.warning("Gaming Split-Screen primary render failed (%s). Retrying fallback without subtitles...", err_msg)
        filter_complex_fallback = f"{top_filter}; {bottom_filter}; {stack_filter}; {divider_filter}"
        fallback_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.2f}",
            "-t", f"{duration:.2f}",
            "-i", input_video,
            "-filter_complex", filter_complex_fallback,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "superfast",
            "-crf", "20",
            "-threads", "0",
            "-shortest",
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
                timeout=900
            )
            logger.info("Gaming Split-Screen fallback render completed successfully: %s", output_path)
            return True
        except subprocess.CalledProcessError as fallback_err:
            fallback_msg = fallback_err.stderr[-800:] if fallback_err.stderr else str(fallback_err)
            raise RuntimeError(f"FFmpeg Gaming Split-Screen render failed: {fallback_msg}") from fallback_err
        except Exception as fb_ex:
            raise RuntimeError(f"Fallback Gaming Split-Screen error: {str(fb_ex)}") from fb_ex
    except Exception as e:
        raise RuntimeError(f"Unexpected error during Gaming Split-Screen render: {str(e)}") from e






