"""
YouTube media fetcher wrapping yt-dlp.
Downloads 16kHz mono WAV audio streams and 1080p video streams cleanly to the temporary workspace.
"""

import os
import logging
from typing import List, Dict, Tuple, Any, Optional

try:
    import yt_dlp  # type: ignore
except ImportError:
    yt_dlp = None  # type: ignore

from config import TEMP_DIR, MAX_FEED_ITEMS, SOURCE_FEED_URL, YOUTUBE_COOKIES_FILE

logger = logging.getLogger(__name__)


class YouTubeFetcher:
    """Class wrapper for fetching metadata and streams from YouTube using yt-dlp."""

    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extracts standard 11-character YouTube video ID from various URL formats."""
        if yt_dlp is None:
            logger.error("yt-dlp is not installed.")
            return ""
        ydl_opts = {"quiet": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("id", "")

    @staticmethod
    def get_latest_videos(feed_url_or_channel: str = SOURCE_FEED_URL, limit: int = MAX_FEED_ITEMS) -> List[Dict[str, str]]:
        """
        Fetches the latest videos from a YouTube channel URL or playlist.
        
        Returns:
            List of dicts with 'id', 'title', and 'url'.
        """
        logger.info("Fetching latest %d video feeds from: %s", limit, feed_url_or_channel)
        if yt_dlp is None:
            logger.error("yt-dlp library is not installed. Skipping feed fetching.")
            return []

        # Split multi-channel comma-separated URLs if provided
        feed_sources = [url.strip() for url in feed_url_or_channel.split(",") if url.strip()]
        logger.info("Fetching latest video feeds from %d channels: %s", len(feed_sources), feed_sources)

        ydl_opts = {
            "extract_flat": True,
            "skip_download": True,
            "playlistend": max(1, limit // len(feed_sources)) if feed_sources else limit,
            "quiet": True
        }
        results: List[Dict[str, str]] = []

        for target_url in feed_sources:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    entries = info.get("entries", []) if info else []
                    for entry in entries[:limit]:
                        v_id = entry.get("id")
                        v_title = entry.get("title", "")
                        if v_id and not any(r["id"] == v_id for r in results):
                            results.append({
                                "id": v_id,
                                "title": v_title,
                                "url": f"https://www.youtube.com/watch?v={v_id}"
                            })
            except Exception as e:
                logger.error("Failed to fetch YouTube feed from %s: %s", target_url, str(e))
        
        logger.info("Retrieved %d candidate videos from feed.", len(results))
        return results

    @staticmethod
    def download_audio(youtube_url: str) -> Tuple[str, str]:
        """
        Downloads audio-only stream from YouTube converted to 16kHz mono WAV format.
        
        Args:
            youtube_url: Full YouTube video URL or ID.
            
        Returns:
            Tuple of (video_id, audio_wav_filepath).
        """
        output_template = os.path.join(TEMP_DIR, "%(id)s_audio.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb"]
                }
            },
            "user_agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
            "nocheckcertificate": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }, {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }],
            "postprocessor_args": [
                "-ar", "16000",  # 16kHz sample rate for Whisper
                "-ac", "1",      # Mono channel
            ],
            "quiet": True,
            "overwrites": True
        }

        # Inject YouTube cookies for datacenter bot bypass
        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path):
            ydl_opts["cookiefile"] = cookies_path
            logger.info("Using YouTube cookies file for authenticated download: %s", cookies_path)

        logger.info("Downloading 16kHz mono audio for: %s", youtube_url)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_id = info.get("id", "")
            audio_path = os.path.join(TEMP_DIR, f"{video_id}_audio.wav")
            
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Expected audio file missing after download: {audio_path}")

        logger.info("Audio downloaded successfully: %s", audio_path)
        return video_id, audio_path

    @staticmethod
    def download_video_stream(youtube_url: str, start_sec: Optional[float] = None, end_sec: Optional[float] = None) -> str:
        """
        Downloads high quality video stream (up to 1080p MP4).
        If start_sec and end_sec are provided, downloads ONLY the specific clip slice (50x faster!).
        
        Args:
            youtube_url: Full YouTube video URL or ID.
            start_sec: Optional start timestamp in seconds.
            end_sec: Optional end timestamp in seconds.
            
        Returns:
            Path to downloaded MP4 video file.
        """
        output_template = os.path.join(TEMP_DIR, "%(id)s_video.%(ext)s")
        ydl_opts = {
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
            "outtmpl": output_template,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb"]
                }
            },
            "user_agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
            "nocheckcertificate": True,
            "quiet": True,
            "overwrites": True
        }

        # Inject YouTube cookies for datacenter bot bypass
        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path):
            ydl_opts["cookiefile"] = cookies_path

        if start_sec is not None and end_sec is not None:
            # Buffer 3s before and after to ensure clean FFmpeg keyframe trimming
            pad_start = max(0.0, start_sec - 3.0)
            pad_end = end_sec + 3.0
            try:
                import yt_dlp.utils
                ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(pad_start, pad_end)])
                ydl_opts["force_keyframes_at_cuts"] = True
                logger.info("Downloading fast 1080p clip slice (%.2fs - %.2fs) for: %s", pad_start, pad_end, youtube_url)
            except Exception as e:
                logger.warning("Fast section download not supported by yt-dlp version, falling back: %s", str(e))
        else:
            logger.info("Downloading 1080p MP4 video stream for: %s", youtube_url)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_id = info.get("id", "")
            
            # Find the actual saved file path
            video_path = os.path.join(TEMP_DIR, f"{video_id}_video.mp4")
            if not os.path.exists(video_path):
                # Fallback check if yt-dlp preserved a different extension
                for ext in ["mp4", "mkv", "webm"]:
                    alt_path = os.path.join(TEMP_DIR, f"{video_id}_video.{ext}")
                    if os.path.exists(alt_path):
                        video_path = alt_path
                        break
                        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Expected video file missing after download: {video_path}")

        logger.info("Video stream ready: %s", video_path)
        return video_path
