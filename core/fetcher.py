"""
YouTube media fetcher — 5-Layer Anti-Bot Defense System.

Layer 1: youtube_transcript_api (caption endpoint — lightest, no video download)
Layer 2: pytubefix with auto PO Token generation (needs Node.js on VPS)
Layer 3: pytubefix with OAuth cache (tokens.json transferred from local machine)
Layer 4: yt-dlp with cookies.txt + aggressive client rotation
Layer 5: yt-dlp bare fallback (last resort)

Downloads 16kHz mono WAV audio streams and 1080p video streams cleanly to the temporary workspace.
"""

import os
import re
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

try:
    import yt_dlp  # type: ignore
except ImportError:
    yt_dlp = None  # type: ignore

from config import TEMP_DIR, MAX_FEED_ITEMS, SOURCE_FEED_URL, YOUTUBE_COOKIES_FILE, BASE_DIR

logger = logging.getLogger(__name__)

# Path to OAuth token cache for pytubefix (can be pre-seeded from local machine)
OAUTH_CACHE_DIR = BASE_DIR / "config" / "oauth_cache"
os.makedirs(OAUTH_CACHE_DIR, exist_ok=True)


def _build_pytubefix_yt(youtube_url: str, client: str = 'MWEB', use_oauth: bool = False):
    """
    Build a pytubefix YouTube object with the specified client and optional OAuth cache.
    Returns the YouTube object or raises an exception.
    """
    import pytubefix  # type: ignore

    kwargs = {}

    if use_oauth:
        kwargs['use_oauth'] = True
        kwargs['allow_oauth_cache'] = True
        token_file = OAUTH_CACHE_DIR / "tokens.json"
        if token_file.exists():
            kwargs['token_file'] = str(token_file)

    yt = pytubefix.YouTube(youtube_url, client=client, **kwargs)
    return yt


def _parse_srt_to_transcript(srt_text: str) -> Optional[Dict[str, Any]]:
    """Parse SRT caption text into our standard transcript format."""
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

            match = re.match(
                r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)",
                time_line
            )
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

    if not segments:
        return None

    return {
        "text": " ".join(full_text_parts),
        "segments": segments,
        "words": words
    }


def is_valid_mp4_video(file_path: str) -> bool:
    """Verifies that an MP4 video file exists, is non-zero, and readable (no 'moov atom not found')."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 100000:
        return False
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return False
        ret, frame = cap.read()
        cap.release()
        return ret and frame is not None
    except Exception:
        return False


class YouTubeFetcher:
    """Class wrapper for fetching metadata and streams from YouTube — 5-Layer Anti-Bot Defense."""

    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extracts standard 11-character YouTube video ID from various URL formats."""
        match = re.search(
            r"(?:v=|\/live\/|\/shorts\/|\/embed\/|youtu\.be\/|\/v\/|e\/|watch\?v=)([^#\&\?\/]{11})",
            url
        )
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

    # -------------------------------------------------------------------------
    # TRANSCRIPT FETCHING — 3-Layer Defense
    # -------------------------------------------------------------------------

    @staticmethod
    def fetch_transcript(video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches official YouTube transcript/captions using a 3-layer defense:
        
        Layer 1: youtube_transcript_api (lightest — no video access needed)
        Layer 2: pytubefix captions with auto PO Token (MWEB/WEB client rotation)
        Layer 3: pytubefix captions with OAuth cache
        """
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # ── LAYER 1: youtube_transcript_api ──────────────────────────────────
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            ytt = YouTubeTranscriptApi()
            transcript_list = None

            try:
                transcript_list = ytt.fetch(video_id, languages=['id', 'en', 'id-ID', 'en-US'])
            except Exception as e_clean:
                logger.debug("L1 primary language fetch for %s: %s", video_id, str(e_clean))

            if not transcript_list:
                try:
                    list_func = getattr(ytt, 'list_transcripts', None) or getattr(YouTubeTranscriptApi, 'list_transcripts', None)
                    if list_func:
                        transcripts = list_func(video_id)
                        t_obj = next(iter(transcripts), None)
                        if t_obj:
                            transcript_list = t_obj.fetch()
                except Exception as e_list:
                    logger.debug("L1 transcript list fetch for %s: %s", video_id, str(e_list))

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
                logger.info("✅ [L1] youtube_transcript_api SUCCESS for %s: %d segments", video_id, len(segments))
                return {"text": full_text, "segments": segments, "words": words}
        except Exception as e_api:
            logger.warning("❌ [L1] youtube_transcript_api failed for %s: %s", video_id, str(e_api))

        # ── LAYER 2: pytubefix captions with auto PO Token ───────────────────
        caption_codes = ['a.id', 'id', 'id-ID', 'a.en', 'en', 'en-US']

        for c_mode in ['MWEB', 'WEB']:
            try:
                yt = _build_pytubefix_yt(youtube_url, client=c_mode)
                caption = None
                for c_code in caption_codes:
                    try:
                        caption = yt.captions[c_code]
                        break
                    except KeyError:
                        continue

                if not caption and yt.captions:
                    caption = next(iter(yt.captions), None)

                if caption:
                    result = _parse_srt_to_transcript(caption.generate_srt_captions())
                    if result:
                        logger.info("✅ [L2] pytubefix PO Token (%s) SUCCESS for %s: %d segments",
                                    c_mode, video_id, len(result['segments']))
                        return result
            except Exception as e_ptf:
                logger.warning("❌ [L2] pytubefix PO Token (%s) failed for %s: %s", c_mode, video_id, str(e_ptf))

        # ── LAYER 3: pytubefix captions with OAuth cache ─────────────────────
        oauth_token_file = OAUTH_CACHE_DIR / "tokens.json"
        if oauth_token_file.exists():
            for c_mode in ['MWEB', 'WEB']:
                try:
                    yt = _build_pytubefix_yt(youtube_url, client=c_mode, use_oauth=True)
                    caption = None
                    for c_code in caption_codes:
                        try:
                            caption = yt.captions[c_code]
                            break
                        except KeyError:
                            continue

                    if not caption and yt.captions:
                        caption = next(iter(yt.captions), None)

                    if caption:
                        result = _parse_srt_to_transcript(caption.generate_srt_captions())
                        if result:
                            logger.info("✅ [L3] pytubefix OAuth (%s) SUCCESS for %s: %d segments",
                                        c_mode, video_id, len(result['segments']))
                            return result
                except Exception as e_oauth:
                    logger.warning("❌ [L3] pytubefix OAuth (%s) failed for %s: %s", c_mode, video_id, str(e_oauth))
        else:
            logger.debug("[L3] No OAuth cache at %s — skipping OAuth layer", oauth_token_file)

        logger.error("❌ ALL transcript layers exhausted for %s", video_id)
        return None

    # -------------------------------------------------------------------------
    # AUDIO DOWNLOAD — 5-Layer Defense
    # -------------------------------------------------------------------------

    @staticmethod
    def download_audio(youtube_url: str) -> Tuple[str, str]:
        """
        Downloads audio-only stream from YouTube converted to 16kHz mono WAV.
        
        5-Layer Defense:
        Layer 1: pytubefix MWEB/WEB with auto PO Token + FFmpeg
        Layer 2: pytubefix MWEB/WEB with OAuth cache + FFmpeg
        Layer 3: yt-dlp with cookies.txt + mweb client priority
        Layer 4: yt-dlp with aggressive client rotation (no cookies)
        Layer 5: yt-dlp bare minimum fallback
        """
        video_id = YouTubeFetcher.extract_video_id(youtube_url) or "custom"
        audio_path = os.path.join(TEMP_DIR, f"{video_id}_audio.wav")

        logger.info("🔊 Downloading 16kHz mono audio for: %s", youtube_url)

        # ── LAYER 1: pytubefix with auto PO Token ───────────────────────────
        for c_mode in ['MWEB', 'WEB']:
            try:
                yt = _build_pytubefix_yt(youtube_url, client=c_mode)
                stream = yt.streams.get_audio_only()
                if stream and stream.url:
                    logger.info("[L1] Extracted pytubefix audio URL (client=%s, po_token=auto). Converting...", c_mode)
                    ffmpeg_cmd = [
                        "ffmpeg", "-y",
                        "-i", stream.url,
                        "-ar", "16000",
                        "-ac", "1",
                        audio_path
                    ]
                    subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, check=True, timeout=120)
                    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                        logger.info("✅ [L1] Audio downloaded via pytubefix PO Token (%s): %s", c_mode, audio_path)
                        return video_id, audio_path
            except Exception as e1:
                logger.warning("❌ [L1] pytubefix PO Token audio (%s) failed: %s", c_mode, str(e1)[:200])

        # ── LAYER 2: pytubefix with OAuth cache ─────────────────────────────
        oauth_token_file = OAUTH_CACHE_DIR / "tokens.json"
        if oauth_token_file.exists():
            for c_mode in ['MWEB', 'WEB']:
                try:
                    yt = _build_pytubefix_yt(youtube_url, client=c_mode, use_oauth=True)
                    stream = yt.streams.get_audio_only()
                    if stream and stream.url:
                        logger.info("[L2] Extracted pytubefix audio URL (client=%s, oauth=cached). Converting...", c_mode)
                        ffmpeg_cmd = [
                            "ffmpeg", "-y",
                            "-i", stream.url,
                            "-ar", "16000",
                            "-ac", "1",
                            audio_path
                        ]
                        subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, check=True, timeout=120)
                        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                            logger.info("✅ [L2] Audio downloaded via pytubefix OAuth (%s): %s", c_mode, audio_path)
                            return video_id, audio_path
                except Exception as e2:
                    logger.warning("❌ [L2] pytubefix OAuth audio (%s) failed: %s", c_mode, str(e2)[:200])

        # ── LAYER 3: yt-dlp with cookies + mweb client priority ─────────────
        cookies_path = str(YOUTUBE_COOKIES_FILE)
        has_cookies = os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 10

        if has_cookies:
            try:
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
                    "postprocessor_args": ["-ar", "16000", "-ac", "1"],
                    "quiet": True,
                    "overwrites": True,
                    "cookiefile": cookies_path,
                    "extractor_args": {"youtube": {"player_client": ["mweb", "web_creator", "android", "ios"]}}
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    v_id = info.get("id", video_id)
                    audio_path = os.path.join(TEMP_DIR, f"{v_id}_audio.wav")
                    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                        logger.info("✅ [L3] Audio downloaded via yt-dlp + cookies: %s", audio_path)
                        return v_id, audio_path
            except Exception as e3:
                logger.warning("❌ [L3] yt-dlp + cookies audio failed: %s", str(e3)[:200])

        # ── LAYER 4: yt-dlp aggressive client rotation (no cookies) ──────────
        try:
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
                "postprocessor_args": ["-ar", "16000", "-ac", "1"],
                "quiet": True,
                "overwrites": True,
                "extractor_args": {"youtube": {"player_client": ["mweb", "android", "web_creator", "ios"]}}
            }

            if has_cookies:
                ydl_opts["cookiefile"] = cookies_path

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                v_id = info.get("id", video_id)
                audio_path = os.path.join(TEMP_DIR, f"{v_id}_audio.wav")
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                    logger.info("✅ [L4] Audio downloaded via yt-dlp client rotation: %s", audio_path)
                    return v_id, audio_path
        except Exception as e4:
            logger.warning("❌ [L4] yt-dlp client rotation audio failed: %s", str(e4)[:200])

        # ── LAYER 5: yt-dlp bare minimum fallback ────────────────────────────
        try:
            output_template = os.path.join(TEMP_DIR, "%(id)s_audio.%(ext)s")
            ydl_opts = {
                "format": "ba/b/best",
                "outtmpl": output_template,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "192",
                }],
                "postprocessor_args": ["-ar", "16000", "-ac", "1"],
                "quiet": True,
                "overwrites": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                v_id = info.get("id", video_id)
                audio_path = os.path.join(TEMP_DIR, f"{v_id}_audio.wav")
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                    logger.info("✅ [L5] Audio downloaded via yt-dlp bare fallback: %s", audio_path)
                    return v_id, audio_path
        except Exception as e5:
            logger.error("❌ [L5] ALL 5 audio download layers EXHAUSTED for %s: %s", youtube_url, str(e5)[:300])
            raise RuntimeError(
                f"Semua 5 metode download audio gagal untuk {youtube_url}. "
                f"Kemungkinan besar IP VPS diblokir YouTube. "
                f"Solusi: (1) Pasang Node.js di VPS untuk auto PO Token, "
                f"(2) Salin OAuth tokens.json ke {OAUTH_CACHE_DIR}, "
                f"(3) Ekspor cookies.txt dari browser ke {YOUTUBE_COOKIES_FILE}"
            ) from e5

        return video_id, audio_path

    # -------------------------------------------------------------------------
    # VIDEO STREAM DOWNLOAD — 5-Layer Defense
    # -------------------------------------------------------------------------

    @staticmethod
    def download_video_stream(youtube_url: str, start_sec: Optional[float] = None, end_sec: Optional[float] = None) -> str:
        """
        Downloads high-quality video stream with 5-Layer Anti-Bot Defense.
        
        Layer 1: pytubefix MWEB/WEB with auto PO Token + FFmpeg slice
        Layer 2: pytubefix MWEB/WEB with OAuth cache + FFmpeg slice
        Layer 3: yt-dlp with cookies + client rotation
        Layer 4: yt-dlp aggressive client rotation (no cookies)
        Layer 5: yt-dlp bare fallback
        """
        video_id = YouTubeFetcher.extract_video_id(youtube_url) or "custom"
        output_path = os.path.join(TEMP_DIR, f"{video_id}_video.mp4")

        start_s = max(0.0, float(start_sec or 0.0))
        dur_s = max(10.0, float(end_sec or 30.0) - start_s) if end_sec else None

        if os.path.exists(output_path):
            if is_valid_mp4_video(output_path):
                logger.info("✅ Verified valid video stream in temp: %s", output_path)
                return output_path
            else:
                logger.warning("⚠️ Corrupted MP4 file detected in temp ('moov atom not found' or unreadable). Purging: %s", output_path)
                try:
                    os.remove(output_path)
                except Exception:
                    pass

        logger.info("🎬 Downloading video stream (Start: %.1fs, Duration: %s) -> %s",
                    start_s, f"{dur_s:.1f}s" if dur_s else "FULL", output_path)

        def _ffmpeg_slice_from_url(stream_url: str) -> bool:
            """Slice video from stream URL using FFmpeg. Returns True if successful."""
            ffmpeg_cmd = ["ffmpeg", "-y"]
            if start_s > 0:
                ffmpeg_cmd.extend(["-ss", f"{start_s:.2f}"])
            if dur_s:
                ffmpeg_cmd.extend(["-t", f"{dur_s:.2f}"])
            ffmpeg_cmd.extend([
                "-i", stream_url,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "17",
                "-c:a", "aac",
                output_path
            ])
            subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, check=True, timeout=300)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 100000

        # ── LAYER 1: pytubefix with auto PO Token ───────────────────────────
        for c_mode in ['MWEB', 'WEB']:
            try:
                yt = _build_pytubefix_yt(youtube_url, client=c_mode)
                stream = (yt.streams.filter(adaptive=True, file_extension="mp4", only_video=True).order_by("resolution").desc().first()
                          or yt.streams.filter(file_extension="mp4").get_highest_resolution()
                          or yt.streams.get_highest_resolution())
                if stream and stream.url:
                    logger.info("[L1] Extracted 1080p pytubefix video URL (client=%s, resolution=%s). Slicing...", c_mode, getattr(stream, 'resolution', 'HD'))
                    if _ffmpeg_slice_from_url(stream.url):
                        logger.info("✅ [L1] High-Res Video slice via pytubefix PO Token (%s): %s", c_mode, output_path)
                        return output_path
            except Exception as e1:
                logger.warning("❌ [L1] pytubefix PO Token video (%s) failed: %s", c_mode, str(e1)[:200])

        # ── LAYER 2: pytubefix with OAuth cache ─────────────────────────────
        oauth_token_file = OAUTH_CACHE_DIR / "tokens.json"
        if oauth_token_file.exists():
            for c_mode in ['MWEB', 'WEB']:
                try:
                    yt = _build_pytubefix_yt(youtube_url, client=c_mode, use_oauth=True)
                    stream = (yt.streams.filter(adaptive=True, file_extension="mp4", only_video=True).order_by("resolution").desc().first()
                              or yt.streams.filter(file_extension="mp4").get_highest_resolution()
                              or yt.streams.get_highest_resolution())
                    if stream and stream.url:
                        logger.info("[L2] Extracted 1080p pytubefix video URL (client=%s, oauth=cached, res=%s). Slicing...", c_mode, getattr(stream, 'resolution', 'HD'))
                        if _ffmpeg_slice_from_url(stream.url):
                            logger.info("✅ [L2] High-Res Video slice via pytubefix OAuth (%s): %s", c_mode, output_path)
                            return output_path
                except Exception as e2:
                    logger.warning("❌ [L2] pytubefix OAuth video (%s) failed: %s", c_mode, str(e2)[:200])

        # ── LAYER 3: yt-dlp with cookies + client rotation ──────────────────
        cookies_path = str(YOUTUBE_COOKIES_FILE)
        has_cookies = os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 10

        if has_cookies:
            try:
                ydl_opts = {
                    "format": "bestvideo[height>=1080]+bestaudio/bestvideo[height>=720]+bestaudio/best",
                    "outtmpl": output_path,
                    "nocheckcertificate": True,
                    "quiet": True,
                    "overwrites": True,
                    "cookiefile": cookies_path,
                    "extractor_args": {"youtube": {"player_client": ["mweb", "web_creator", "android", "ios"]}}
                }
                if start_sec is not None and end_sec is not None:
                    ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start_sec), float(end_sec))])
                    ydl_opts["force_keyframes_at_cuts"] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([youtube_url])
                if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                    logger.info("✅ [L3] 1080p Video downloaded via yt-dlp + cookies: %s", output_path)
                    return output_path
            except Exception as e3:
                logger.warning("❌ [L3] yt-dlp + cookies video failed: %s", str(e3)[:200])

        # ── LAYER 4: yt-dlp aggressive client rotation ───────────────────────
        try:
            ydl_opts = {
                "format": "bestvideo[height>=1080]+bestaudio/bestvideo[height>=720]+bestaudio/best",
                "outtmpl": output_path,
                "nocheckcertificate": True,
                "quiet": True,
                "overwrites": True,
                "extractor_args": {"youtube": {"player_client": ["mweb", "android", "web_creator", "ios"]}}
            }
            if has_cookies:
                ydl_opts["cookiefile"] = cookies_path
            if start_sec is not None and end_sec is not None:
                ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start_sec), float(end_sec))])
                ydl_opts["force_keyframes_at_cuts"] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([youtube_url])
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                logger.info("✅ [L4] 1080p Video downloaded via yt-dlp client rotation: %s", output_path)
                return output_path
        except Exception as e4:
            logger.warning("❌ [L4] yt-dlp client rotation video failed: %s", str(e4)[:200])

        # ── LAYER 5: yt-dlp bare fallback ────────────────────────────────────
        try:
            ydl_opts = {
                "format": "b/best",
                "outtmpl": output_path,
                "quiet": True,
                "overwrites": True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])

            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                logger.info("✅ [L5] Video downloaded via yt-dlp bare fallback: %s", output_path)
                return output_path
        except Exception as e5:
            logger.error("❌ [L5] ALL 5 video download layers EXHAUSTED for %s: %s", youtube_url, str(e5)[:300])

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
            raise FileNotFoundError(
                f"Semua 5 metode download video gagal untuk {youtube_url}. "
                f"IP VPS kemungkinan diblokir YouTube. "
                f"Solusi: (1) Install Node.js di VPS, "
                f"(2) Salin OAuth tokens.json ke {OAUTH_CACHE_DIR}, "
                f"(3) Ekspor cookies.txt ke {YOUTUBE_COOKIES_FILE}"
            )

        logger.info("Video stream ready (%d MB): %s", os.path.getsize(output_path) // (1024 * 1024), output_path)
        return output_path
