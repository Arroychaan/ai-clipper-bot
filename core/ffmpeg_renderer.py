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

    overlay_filter = "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
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
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    logger.info("Executing FFmpeg render command...")
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
        logger.error("FFmpeg render failed with exit code %d. Error output:\n%s",
                     e.returncode, e.stderr[-1000:] if e.stderr else "")
        return False
    except Exception as e:
        logger.error("Unexpected error during FFmpeg rendering: %s", str(e))
        return False
