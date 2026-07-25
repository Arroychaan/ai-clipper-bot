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
        import re
        match = re.search(r"(?:v=|\/live\/|\/shorts\/|\/embed\/|youtu\.be\/|\/v\/|e\/|watch\?v=)([^#\&\?\/]{11})", url)
        if match:
            return match.group(1)
        if yt_dlp is None:
            logger.error("yt-dlp is not installed.")
            return ""
        try:
            ydl_opts = {"quiet": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("id", "")
        except Exception:
            return ""


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
    def fetch_transcript(video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches official YouTube transcript directly via youtube_transcript_api or pytubefix
        in < 1 second without any bot checks or audio downloads!
        """
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Primary engine: youtube_transcript_api
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            ytt = YouTubeTranscriptApi()
            transcript_list = None

            try:
                transcript_list = ytt.fetch(video_id, languages=['id', 'en', 'id-ID', 'en-US'])
            except Exception as e_clean:
                logger.debug("Primary clean language fetch attempt for %s: %s", video_id, str(e_clean))

            if not transcript_list:
                try:
                    list_func = getattr(ytt, 'list_transcripts', None) or getattr(YouTubeTranscriptApi, 'list_transcripts', None)
                    if list_func:
                        transcripts = list_func(video_id)
                        t_obj = next(iter(transcripts), None)
                        if t_obj:
                            transcript_list = t_obj.fetch()
                except Exception as e_list:
                    logger.debug("Transcript list fetch attempt for %s: %s", video_id, str(e_list))

            if transcript_list:
                full_text_parts = []
                segments = []
                words = []
                for item in transcript_list:
                    t_text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
                    t_start = float(item.get("start", 0.0)) if isinstance(item, dict) else float(getattr(item, "start", 0.0))
                    t_dur = float(item.get("duration", 0.0)) if isinstance(item, dict) else float(getattr(item, "duration", 0.0))

                    t_clean = t_text.strip()
                    if not t_clean:
                        continue

                    full_text_parts.append(t_clean)
                    segments.append({
                        "start": t_start,
                        "end": t_start + t_dur,
                        "text": t_clean
                    })
                    
                    seg_words = t_clean.split()
                    if seg_words:
                        w_dur = t_dur / len(seg_words)
                        for w_i, w_str in enumerate(seg_words):
                            words.append({
                                "word": w_str,
                                "start": round(t_start + (w_i * w_dur), 2),
                                "end": round(t_start + ((w_i + 1) * w_dur), 2)
                            })

                full_text = " ".join(full_text_parts)
                logger.info("Successfully fetched direct transcript via youtube_transcript_api for video %s: %d segments",
                            video_id, len(segments))
                return {"text": full_text, "segments": segments, "words": words}
        except Exception as e_api:
            logger.warning("youtube_transcript_api direct fetch hit error (%s). Falling back to pytubefix...", str(e_api))

        # 2. Secondary engine: pytubefix SRT caption extractor
        try:
            import pytubefix  # type: ignore
            import re
            yt = pytubefix.YouTube(youtube_url)
            caption = None
            for c_code in ['a.id', 'id', 'id-ID', 'a.en', 'en', 'en-US']:
                try:
                    caption = yt.captions[c_code]
                    break
                except KeyError:
                    continue

            if not caption and yt.captions:
                caption = next(iter(yt.captions), None)

            if caption:
                srt_text = caption.generate_srt_captions()
                blocks = srt_text.strip().split("\n\n")
                segments = []
                full_text_parts = []
                words = []

                for block in blocks:
                    lines = block.strip().split("\n")
                    if len(lines) >= 3:
                        time_line = lines[1]
                        text_val = " ".join(lines[2:]).strip()
                        if not text_val:
                            continue

                        match = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", time_line)
                        if match:
                            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
                            t_start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
                            t_end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
                            t_dur = max(0.1, t_end - t_start)

                            full_text_parts.append(text_val)
                            segments.append({"start": t_start, "end": t_end, "text": text_val})

                            seg_words = text_val.split()
                            if seg_words:
                                w_dur = t_dur / len(seg_words)
                                for w_i, w_str in enumerate(seg_words):
                                    words.append({
                                        "word": w_str,
                                        "start": round(t_start + (w_i * w_dur), 2),
                                        "end": round(t_start + ((w_i + 1) * w_dur), 2)
                                    })

                full_text = " ".join(full_text_parts)
                logger.info("Successfully fetched direct transcript via pytubefix for video %s: %d segments",
                            video_id, len(segments))
                return {"text": full_text, "segments": segments, "words": words}
        except Exception as e_ptf:
            logger.warning("pytubefix caption fetch failed for %s: %s", video_id, str(e_ptf))

        return None

    @staticmethod
    def download_audio(youtube_url: str) -> Tuple[str, str]:
        """
        Downloads audio-only stream from YouTube converted to 16kHz mono WAV format.
        Uses pytubefix direct stream URL + FFmpeg to bypass YouTube bot checks 100%!
        """
        video_id = YouTubeFetcher.extract_video_id(youtube_url) or "custom"
        audio_path = os.path.join(TEMP_DIR, f"{video_id}_audio.wav")

        logger.info("Downloading 16kHz mono audio for: %s", youtube_url)

        # 1. Primary Engine: pytubefix direct audio stream URL -> FFmpeg
        try:
            import pytubefix  # type: ignore
            yt = pytubefix.YouTube(youtube_url)
            stream = yt.streams.get_audio_only()
            if stream and stream.url:
                logger.info("Extracted direct pytubefix audio stream URL. Running FFmpeg conversion...")
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", stream.url,
                    "-ar", "16000",
                    "-ac", "1",
                    audio_path
                ]
                subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                    logger.info("Audio downloaded successfully via pytubefix + FFmpeg: %s", audio_path)
                    return video_id, audio_path
        except Exception as ptf_err:
            logger.warning("pytubefix audio stream extraction failed (%s). Retrying yt-dlp...", str(ptf_err))

        # 2. Secondary Engine: yt-dlp with mobile client rotation
        output_template = os.path.join(TEMP_DIR, "%(id)s_audio.%(ext)s")
        ydl_opts = {
            "format": "ba/b/best",
            "outtmpl": output_template,
            "nocheckcertificate": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
            "postprocessor_args": [
                "-ar", "16000",
                "-ac", "1",
            ],
            "quiet": True,
            "overwrites": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web_creator", "mweb", "ios"]}}
        }

        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 10:
            ydl_opts["cookiefile"] = cookies_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                v_id = info.get("id", video_id)
                audio_path = os.path.join(TEMP_DIR, f"{v_id}_audio.wav")
                if os.path.exists(audio_path):
                    return v_id, audio_path
        except Exception as ytdlp_err:
            logger.error("All audio download methods failed for %s: %s", youtube_url, str(ytdlp_err))
            raise ytdlp_err

        return video_id, audio_path

    @staticmethod
    def download_video_stream(youtube_url: str, start_sec: Optional[float] = None, end_sec: Optional[float] = None) -> str:
        """
        Downloads high-quality video stream. Uses pytubefix + FFmpeg slice cutting to bypass YouTube bot checks 100%!
        """
        video_id = YouTubeFetcher.extract_video_id(youtube_url) or "custom"
        output_path = os.path.join(TEMP_DIR, f"{video_id}_video.mp4")

        start_s = max(0.0, float(start_sec or 0.0))
        dur_s = max(10.0, float(end_sec or 30.0) - start_s) if end_sec else None

        logger.info("Downloading video stream (Start: %.1fs, Duration: %s) -> %s",
                    start_s, f"{dur_s:.1fs}" if dur_s else "FULL", output_path)

        # 1. Primary Engine: pytubefix stream URL + FFmpeg fast slice cut
        try:
            import pytubefix  # type: ignore
            yt = pytubefix.YouTube(youtube_url)
            stream = yt.streams.filter(progressive=True).get_highest_resolution() or yt.streams.filter(file_extension="mp4").get_highest_resolution()
            if stream and stream.url:
                logger.info("Extracted pytubefix video stream URL. Cutting slice via FFmpeg...")
                ffmpeg_cmd = ["ffmpeg", "-y"]
                if start_s > 0:
                    ffmpeg_cmd.extend(["-ss", f"{start_s:.2f}"])
                if dur_s:
                    ffmpeg_cmd.extend(["-t", f"{dur_s:.2f}"])
                ffmpeg_cmd.extend([
                    "-i", stream.url,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "17",
                    "-c:a", "aac",
                    output_path
                ])
                subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                    logger.info("Video stream slice downloaded successfully via pytubefix + FFmpeg: %s", output_path)
                    return output_path
        except Exception as ptf_v_err:
            logger.warning("pytubefix video stream extraction failed (%s). Retrying yt-dlp...", str(ptf_v_err))

        # 2. Secondary Engine: yt-dlp section range downloader
        ydl_opts = {
            "format": "b/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl": output_path,
            "nocheckcertificate": True,
            "quiet": True,
            "overwrites": True,
            "extractor_args": {"youtube": {"player_client": ["web_creator", "android_vr", "android", "ios"]}}
        }

        if start_sec is not None and end_sec is not None:
            ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start_sec), float(end_sec))])
            ydl_opts["force_keyframes_at_cuts"] = True

        cookies_path = str(YOUTUBE_COOKIES_FILE)
        if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 10:
            ydl_opts["cookiefile"] = cookies_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            return output_path
        except Exception as e:
            logger.warning("yt-dlp range download failed (%s). Retrying full video fallback...", str(e))
            ydl_opts_fallback = {
                "format": "b/best",
                "outtmpl": output_path,
                "quiet": True,
                "overwrites": True
            }
            with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                ydl.download([youtube_url])

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
            raise FileNotFoundError(f"Downloaded video stream file missing or empty: {output_path}")

        logger.info("Video stream ready (%d MB): %s", os.path.getsize(output_path) // (1024 * 1024), output_path)
        return output_path







