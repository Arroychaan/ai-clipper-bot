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
    def get_transcript_direct(video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches official YouTube transcript directly via youtube_transcript_api
        in 0.05 seconds without any bot checks or audio downloads!
        Supports both v1.2+ (fetch) and v0.6+ (get_transcript/list) API signatures.
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            
            transcript_list = None
            # 1. Try v1.2+ API (YouTubeTranscriptApi().fetch)
            try:
                ytt = YouTubeTranscriptApi()
                if hasattr(ytt, 'fetch'):
                    try:
                        transcript_list = ytt.fetch(video_id, languages=['id', 'en', 'en-US', 'a.id', 'a.en'])
                    except Exception:
                        transcript_list = ytt.fetch(video_id)
            except Exception:
                pass

            # 2. Try v0.6+ static API (YouTubeTranscriptApi.get_transcript)
            if transcript_list is None and hasattr(YouTubeTranscriptApi, 'get_transcript'):
                try:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en', 'en-US', 'a.id', 'a.en'])
                except Exception:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

            # 3. Try listing transcripts
            if transcript_list is None:
                try:
                    list_func = getattr(YouTubeTranscriptApi, 'list', None) or getattr(YouTubeTranscriptApi, 'list_transcripts', None)
                    if list_func:
                        transcripts = list_func(video_id)
                        t_obj = next(iter(transcripts), None)
                        if t_obj:
                            transcript_list = t_obj.fetch()
                except Exception:
                    pass

            if not transcript_list:
                logger.warning("No transcript snippets retrieved for video %s", video_id)
                return None

            full_text_parts = []
            segments = []
            for item in transcript_list:
                if isinstance(item, dict):
                    t_text = item.get("text", "")
                    t_start = float(item.get("start", 0.0))
                    t_dur = float(item.get("duration", 0.0))
                else:
                    t_text = getattr(item, "text", "")
                    t_start = float(getattr(item, "start", 0.0))
                    t_dur = float(getattr(item, "duration", 0.0))

                full_text_parts.append(t_text)
                segments.append({
                    "start": t_start,
                    "end": t_start + t_dur,
                    "text": t_text
                })

            full_text = " ".join(full_text_parts)
            logger.info("Successfully fetched direct YouTube transcript for video %s: %d segments", video_id, len(segments))
            return {"text": full_text, "segments": segments}
        except Exception as e:
            logger.warning("youtube_transcript_api direct fetch failed for %s: %s", video_id, str(e))
            return None

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

        # Inject YouTube cookies and mobile/Android player client for datacenter bot bypass
        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 100:
            ydl_opts["cookiefile"] = cookies_path

        ydl_opts["user_agent"] = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios", "mweb"]}}

        logger.info("Downloading 16kHz mono audio for: %s", youtube_url)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                video_id = info.get("id", "")
                audio_path = os.path.join(TEMP_DIR, f"{video_id}_audio.wav")
        except Exception as primary_err:
            logger.warning("Primary audio download failed (%s). Retrying without cookies via Android client...", str(primary_err))
            ydl_opts.pop("cookiefile", None)
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios"]}}
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
        Downloads high quality video stream (up to 1080p MP4) for accurate FFmpeg seeking.
        """
        output_template = os.path.join(TEMP_DIR, "%(id)s_video.%(ext)s")

        ydl_opts = {
            "format": "best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
            "outtmpl": output_template,
            "nocheckcertificate": True,
            "quiet": True,
            "overwrites": True
        }

        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 100:
            ydl_opts["cookiefile"] = cookies_path

        ydl_opts["user_agent"] = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios", "mweb"]}}

        def _execute_download(opts: dict) -> Tuple[str, str]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                v_id = info.get("id", "")
                v_path = os.path.join(TEMP_DIR, f"{v_id}_video.mp4")
                if not os.path.exists(v_path):
                    for ext in ["mp4", "mkv", "webm"]:
                        alt_p = os.path.join(TEMP_DIR, f"{v_id}_video.{ext}")
                        if os.path.exists(alt_p):
                            v_path = alt_p
                            break
                return v_id, v_path

        logger.info("Downloading 1080p video stream for FFmpeg precision rendering: %s", youtube_url)
        try:
            video_id, video_path = _execute_download(ydl_opts)
        except Exception as primary_err:
            logger.warning("Primary video download failed (%s). Retrying without cookies...", str(primary_err))
            ydl_opts.pop("cookiefile", None)
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios"]}}
            video_id, video_path = _execute_download(ydl_opts)

        if not os.path.exists(video_path) or os.path.getsize(video_path) < 100000:
            raise FileNotFoundError(f"Downloaded video stream missing or truncated (<100KB): {video_path}")

        logger.info("Video stream ready (%d MB): %s", os.path.getsize(video_path) // (1024 * 1024), video_path)
        return video_path



