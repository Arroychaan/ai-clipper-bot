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


def _escape_ffmpeg_path(path: str) -> str:
    """Escapes backslashes and special chars in file paths for FFmpeg filtergraphs."""
    escaped = path.replace("\\", "/").replace(":", "\\:")
    return repr(escaped).strip("'")


def render_vertical_shorts(
    input_video: str,
    start_time: float,
    duration: float,
    output_path: str,
    subtitle_path: Optional[str] = None
) -> bool:
    """
    Renders a 9:16 vertical video clip using a 1-pass CPU FFmpeg filtergraph.
    
    Layout:
    - Background: Original video scaled to fill 1080x1920 with heavy boxblur (25:10).
    - Foreground: Original video scaled to 1080px width centered vertically with burned-in subtitles.
    
    Args:
        input_video: Path to source MP4 video stream.
        start_time: Clip start timestamp in seconds.
        duration: Duration of clip in seconds.
        output_path: Target path for output MP4 file.
        subtitle_path: Optional path to .srt file to burn into video foreground.
        
    Returns:
        bool: True if render succeeded, False otherwise.
    """
    logger.info(
        "Rendering vertical 9:16 video (Start: %.2fs, Duration: %.2fs) -> %s",
        start_time, duration, output_path
    )

    if not os.path.exists(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return False

    # Base filter graph for background and foreground overlay
    bg_filter = (
        f"[0:v]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=25:10[bg]"
    )
    
    # Subtitle burn-in filter on foreground stream if provided
    if subtitle_path and os.path.exists(subtitle_path):
        escaped_sub_path = _escape_ffmpeg_path(subtitle_path)
        if subtitle_path.endswith(".ass"):
            fg_filter = (
                f"[0:v]scale={TARGET_WIDTH}:-1,"
                f"ass='{escaped_sub_path}'[fg]"
            )
        else:
            sub_style = (
                "Fontsize=22,PrimaryColour=&H00FFFF&,OutlineColour=&H000000&,"
                "BackColour=&H80000000&,Bold=1,Alignment=2,MarginV=120"
            )
            fg_filter = (
                f"[0:v]scale={TARGET_WIDTH}:-1,"
                f"subtitles='{escaped_sub_path}':force_style='{sub_style}'[fg]"
            )
    else:
        fg_filter = f"[0:v]scale={TARGET_WIDTH}:-1[fg]"

    overlay_filter = "[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=60[outv]"
    filter_complex = f"{bg_filter}; {fg_filter}; {overlay_filter}"

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
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    logger.info("Executing FFmpeg Full HD 60fps render command...")
    try:
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        logger.info("FFmpeg render completed successfully: %s", output_path)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("FFmpeg render with subtitles failed (%s). Retrying clean render without subtitles...",
                       e.stderr[-300:] if e.stderr else "")
        # Fallback filter complex without subtitles
        filter_complex_fallback = f"{bg_filter}; f[0:v]scale={TARGET_WIDTH}:-1[fg]; {overlay_filter}".replace("f[0:v]", "[0:v]")
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
            "-crf", "19",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
        try:
            subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            logger.info("Fallback FFmpeg render completed successfully: %s", output_path)
            return True
        except Exception as fallback_err:
            logger.error("Fallback FFmpeg render also failed: %s", str(fallback_err))
            return False
    except Exception as e:
        return False


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

    # Default facecam crop coordinates if not provided (Top-Left 640x480 crop for Windah Basudara)
    fc = facecam_coords or {"crop_w": 640, "crop_h": 480, "crop_x": 0, "crop_y": 0}
    cw, ch, cx, cy = fc.get("crop_w", 640), fc.get("crop_h", 480), fc.get("crop_x", 0), fc.get("crop_y", 0)

    # 1. Top Stream: Streamer Facecam cropped & scaled to 1080x960
    top_filter = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={TARGET_WIDTH}:960:force_original_aspect_ratio=increase,crop={TARGET_WIDTH}:960[top]"

    # 2. Bottom Stream: Gameplay 16:9 center cropped & scaled to 1080x960
    bottom_filter = f"[0:v]scale=-1:960,crop={TARGET_WIDTH}:960[bottom]"

    # 3. Stack Top & Bottom Vertically (Total 1080x1920)
    stack_filter = "[top][bottom]vstack=inputs=2[stacked]"

    # 4. Draw sleek glassmorphic neon divider line across the center (Y=960)
    divider_filter = (
        "[stacked]drawbox=y=956:color=cyan@0.8:width=iw:height=8:t=fill,"
        "drawbox=y=958:color=white@0.9:width=iw:height=4:t=fill[base]"
    )

    # 5. Burn-in Subtitles on gameplay area if provided
    if subtitle_path and os.path.exists(subtitle_path):
        escaped_sub_path = _escape_ffmpeg_path(subtitle_path)
        if subtitle_path.endswith(".ass"):
            final_sub_filter = f"[base]ass='{escaped_sub_path}'[outv]"
        else:
            sub_style = "Fontsize=24,PrimaryColour=&H00FFFF&,OutlineColour=&H000000&,Bold=1,Alignment=2,MarginV=180"
            final_sub_filter = f"[base]subtitles='{escaped_sub_path}':force_style='{sub_style}'[outv]"
    else:
        final_sub_filter = "[base]null[outv]"

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
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    logger.info("Executing Gaming Split-Screen 60fps render command...")
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        logger.info("Gaming Split-Screen render completed successfully: %s", output_path)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Gaming Split-Screen render with subtitles failed (%s). Retrying without subtitles...",
                       e.stderr[-300:] if e.stderr else "")
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
            "-crf", "19",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
        try:
            subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            logger.info("Fallback Gaming Split-Screen render completed successfully: %s", output_path)
            return True
        except Exception as fallback_err:
            logger.error("Fallback Gaming Split-Screen render also failed: %s", str(fallback_err))
            return False
    except Exception as e:
        logger.error("Unexpected error during Gaming Split-Screen rendering: %s", str(e))
        return False



