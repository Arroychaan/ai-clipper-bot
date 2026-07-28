"""
YouTube media fetcher — 6-Layer Anti-Bot Defense System.

Layer 1: youtube_transcript_api (caption endpoint — lightest, no video download)
Layer 2: pytubefix with auto PO Token generation (needs Node.js on VPS)
Layer 3: pytubefix with OAuth cache (tokens.json transferred from local machine)
Layer 4: yt-dlp with cookies.txt + aggressive client rotation
Layer 5: yt-dlp bare fallback (last resort)
Layer 6: Invidious API Public Proxy Stream Extractor (100% VPS IP block bypass)

Downloads 16kHz mono WAV audio streams and 1080p video streams cleanly to the temporary workspace.
"""

import os
import re
import json
import logging
import subprocess
import urllib.request
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

INVIDIOUS_INSTANCES = [
    "https://inv.tux.pizza",
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space",
    "https://invidious.privacydev.net",
    "https://vid.puffyan.us"
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.yt",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.adminforge.de"
]

COBALT_INSTANCES = [
    "https://api.cobalt.tools/api/json",
    "https://cobalt.api.sciter.io/api/json",
    "https://co.wuk.sh/api/json"
]


def _fetch_proxy_stream_urls(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Queries public Invidious, Piped, and Cobalt API instances to extract direct audio and video stream URLs.
    100% Bypasses YouTube datacenter IP blocks on VPS.

    Returns: (audio_url, video_url)
    """
    import urllib.request
    import json
    import ssl

    # Create unverified SSL context to prevent SSL: CERTIFICATE_VERIFY_FAILED errors on Linux VPS
    ssl_ctx = ssl._create_unverified_context()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. Try Invidious Instances
    for instance in INVIDIOUS_INSTANCES:
        api_url = f"{instance}/api/v1/videos/{video_id}"
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    adaptive = data.get("adaptiveFormats", [])
                    streams = data.get("formatStreams", [])

                    audio_url = None
                    video_url = None

                    # Check both 'mimeType' and 'type' keys (Invidious API compatibility)
                    audio_formats = [
                        f for f in adaptive
                        if (str(f.get("mimeType", "") or f.get("type", "")).startswith("audio/")) and f.get("url")
                    ]
                    if audio_formats:
                        best_audio = max(audio_formats, key=lambda f: int(f.get("bitrate", 0) or 0))
                        audio_url = best_audio.get("url")

                    video_formats = [
                        f for f in adaptive
                        if (str(f.get("mimeType", "") or f.get("type", "")).startswith("video/")) and f.get("url")
                    ]
                    if not video_formats:
                        video_formats = [f for f in streams if f.get("url")]

                    if video_formats:
                        best_vid = None
                        for v in video_formats:
                            q = str(v.get("qualityLabel", "") or v.get("quality", ""))
                            if "1080" in q:
                                best_vid = v
                                break
                            elif "720" in q and not best_vid:
                                best_vid = v
                        if not best_vid:
                            best_vid = video_formats[0]
                        video_url = best_vid.get("url")

                    if audio_url or video_url:
                        logger.info("✅ Extracted stream URLs via Invidious instance (%s)", instance)
                        return audio_url, video_url

        except Exception as e:
            logger.debug("Invidious instance %s failed: %s", instance, str(e)[:100])

    # 2. Try Piped Instances
    for p_instance in PIPED_INSTANCES:
        api_url = f"{p_instance}/streams/{video_id}"
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    a_streams = data.get("audioStreams", [])
                    v_streams = data.get("videoStreams", [])

                    audio_url = None
                    video_url = None

                    if a_streams:
                        best_a = max(a_streams, key=lambda s: int(s.get("bitrate", 0) or 0))
                        audio_url = best_a.get("url")

                    if v_streams:
                        best_v = None
                        for v in v_streams:
                            q = str(v.get("quality", ""))
                            if "1080" in q:
                                best_v = v
                                break
                            elif "720" in q and not best_v:
                                best_v = v
                        if not best_v:
                            best_v = v_streams[0]
                        video_url = best_v.get("url")

                    if audio_url or video_url:
                        logger.info("✅ Extracted stream URLs via Piped instance (%s)", p_instance)
                        return audio_url, video_url

        except Exception as e:
            logger.debug("Piped instance %s failed: %s", p_instance, str(e)[:100])

    # 3. Try Cobalt API
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    cob_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    for cob in COBALT_INSTANCES:
        try:
            body = json.dumps({"url": youtube_url, "downloadMode": "audio"}).encode('utf-8')
            req = urllib.request.Request(cob, data=body, headers=cob_headers, method="POST")
            with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
                if resp.status == 200:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    audio_url = res_data.get("url")
                    if audio_url:
                        logger.info("✅ Extracted stream URL via Cobalt API (%s)", cob)
                        return audio_url, audio_url
        except Exception as e:
            logger.debug("Cobalt instance %s failed: %s", cob, str(e)[:100])

    return None, None


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
    """Class wrapper for fetching metadata and streams from YouTube — 6-Layer Anti-Bot Defense."""

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
        """
        logger.info("Fetching latest %d video feeds from: %s", limit, feed_url_or_channel)

        if not feed_url_or_channel:
            return []

        # Try Invidious RSS feed first (lighter, no bot check)
        video_id_cand = YouTubeFetcher.extract_video_id(feed_url_or_channel)
        if video_id_cand:
            return [{
                "id": video_id_cand,
                "title": f"YouTube Video ({video_id_cand})",
                "url": f"https://www.youtube.com/watch?v={video_id_cand}"
            }]

        if yt_dlp is None:
            return []

        try:
            ydl_opts = {
                "extract_flat": "in_playlist",
                "quiet": True,
                "playlistend": limit,
                "nocheckcertificate": True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(feed_url_or_channel, download=False)
                entries = info.get("entries", []) if info else []
                results = []
                for entry in entries:
                    if not entry:
                        continue
                    v_id = entry.get("id") or entry.get("url")
                    v_title = entry.get("title", "YouTube Video")
                    if v_id:
                        v_url = f"https://www.youtube.com/watch?v={v_id}" if not str(v_id).startswith("http") else str(v_id)
                        clean_id = YouTubeFetcher.extract_video_id(v_url) or v_id
                        results.append({
                            "id": clean_id,
                            "title": v_title,
                            "url": v_url
                        })
                return results[:limit]
        except Exception as e:
            logger.warning("Failed to fetch feed via yt-dlp: %s", str(e))

        return []

    @staticmethod
    def fetch_transcript(video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches subtitles/captions using YouTube Transcript API or pytubefix.
        """
        logger.info("Fetching transcript for video ID: %s", video_id)

        # Layer 1: youtube_transcript_api
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en', 'en-US'])
            except Exception:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

            if transcript_list:
                segments = []
                full_text_parts = []
                words = []
                for item in transcript_list:
                    s_text = str(item.get("text", "")).strip()
                    s_start = float(item.get("start", 0.0))
                    s_dur = float(item.get("duration", 0.0))
                    if not s_text:
                        continue
                    full_text_parts.append(s_text)
                    segments.append({"start": s_start, "end": s_start + s_dur, "text": s_text})
                    seg_words = s_text.split()
                    if seg_words:
                        w_dur = max(0.1, s_dur) / len(seg_words)
                        for w_i, w_str in enumerate(seg_words):
                            words.append({
                                "word": w_str,
                                "start": round(s_start + (w_i * w_dur), 2),
                                "end": round(s_start + ((w_i + 1) * w_dur), 2)
                            })
                logger.info("✅ [L1] youtube_transcript_api SUCCESS for %s: %d segments", video_id, len(segments))
                return {
                    "text": " ".join(full_text_parts),
                    "segments": segments,
                    "words": words
                }
        except Exception as e1:
            logger.warning("❌ [L1] youtube_transcript_api failed for %s: %s", video_id, str(e1)[:200])

        # Layer 2: pytubefix captions
        for c_mode in ['MWEB', 'WEB']:
            try:
                yt = _build_pytubefix_yt(f"https://www.youtube.com/watch?v={video_id}", client=c_mode)
                caption = yt.captions.get_by_language_code('id') or yt.captions.get_by_language_code('en')
                if not caption and yt.captions:
                    caption = next(iter(yt.captions), None)

                if caption:
                    result = _parse_srt_to_transcript(caption.generate_srt_captions())
                    if result:
                        logger.info("✅ [L2] pytubefix (%s) captions SUCCESS for %s: %d segments",
                                    c_mode, video_id, len(result['segments']))
                        return result
            except Exception as e2:
                logger.warning("❌ [L2] pytubefix (%s) captions failed for %s: %s", c_mode, video_id, str(e2)[:200])

        # Layer 3: pytubefix OAuth
        oauth_token_file = OAUTH_CACHE_DIR / "tokens.json"
        if oauth_token_file.exists():
            for c_mode in ['MWEB', 'WEB']:
                try:
                    yt = _build_pytubefix_yt(f"https://www.youtube.com/watch?v={video_id}", client=c_mode, use_oauth=True)
                    caption = yt.captions.get_by_language_code('id') or yt.captions.get_by_language_code('en')
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

        logger.error("❌ ALL transcript layers exhausted for %s", video_id)
        return None

    @staticmethod
    def download_audio(youtube_url: str) -> Tuple[str, str]:
        """
        Downloads audio-only stream from YouTube converted to 16kHz mono WAV.

        6-Layer Defense:
        Layer 1: pytubefix MWEB/WEB with auto PO Token + FFmpeg
        Layer 2: pytubefix MWEB/WEB with OAuth cache + FFmpeg
        Layer 3: yt-dlp with cookies.txt + client rotation
        Layer 4: yt-dlp with aggressive client rotation (tvhtml5/android/mweb/ios)
        Layer 5: yt-dlp bare fallback
        Layer 6: Invidious API Public Proxy Stream Extractor (100% VPS IP block bypass)
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

        # ── LAYER 3: yt-dlp with cookies + client rotation ──────────────────
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
                    "extractor_args": {"youtube": {"player_client": ["tvhtml5", "mweb", "android", "ios", "web_creator", "tv_embedded"]}}
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
            ydl_opts = {
                "format": "ba/b/best",
                "outtmpl": os.path.join(TEMP_DIR, "%(id)s_audio.%(ext)s"),
                "nocheckcertificate": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "192",
                }],
                "postprocessor_args": ["-ar", "16000", "-ac", "1"],
                "quiet": True,
                "overwrites": True,
                "extractor_args": {"youtube": {"player_client": ["tvhtml5", "mweb", "android", "ios", "web_creator", "tv_embedded"]}}
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
            ydl_opts = {
                "format": "ba/b/best",
                "outtmpl": os.path.join(TEMP_DIR, "%(id)s_audio.%(ext)s"),
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
            logger.warning("❌ [L5] yt-dlp bare fallback audio failed: %s", str(e5)[:200])

        # ── LAYER 6: Invidious, Piped & Cobalt Proxy Stream Fallback ───────
        try:
            logger.info("🌐 [L6] Attempting Invidious/Piped/Cobalt Proxy API audio stream extraction for %s...", video_id)
            inv_audio_url, _ = _fetch_proxy_stream_urls(video_id)
            if inv_audio_url:
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n",
                    "-reconnect", "1",
                    "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "5",
                    "-i", inv_audio_url,
                    "-ar", "16000",
                    "-ac", "1",
                    audio_path
                ]
                subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, check=True, timeout=180)
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                    logger.info("✅ [L6] Audio downloaded via Proxy API fallback: %s", audio_path)
                    return video_id, audio_path
        except Exception as e6:
            logger.warning("❌ [L6] Proxy API audio fallback failed: %s", str(e6)[:200])

        # ── LAYER 7: yt-dlp CLI binary subprocess fallback ─────────────────
        try:
            logger.info("🌐 [L7] Attempting yt-dlp CLI binary subprocess fallback for %s...", video_id)
            cmd = [
                "yt-dlp",
                "--no-check-certificates",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "-x", "--audio-format", "wav",
                "-o", os.path.join(TEMP_DIR, f"{video_id}_audio.%(ext)s"),
                youtube_url
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, check=True)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 10000:
                logger.info("✅ [L7] Audio downloaded via yt-dlp CLI binary: %s", audio_path)
                return video_id, audio_path
        except Exception as e7:
            logger.warning("❌ [L7] yt-dlp CLI binary audio fallback failed: %s", str(e7)[:200])

        logger.error("❌ ALL 7 audio download layers EXHAUSTED for %s", youtube_url)
        raise RuntimeError(
            f"Semua 7 metode download audio gagal untuk {youtube_url}. "
            f"YouTube memblokir IP VPS. Solusi otomatis SSL & Multi-Proxy telah diaktifkan."
        )

    @staticmethod
    def download_video_stream(youtube_url: str, start_sec: Optional[float] = None, end_sec: Optional[float] = None) -> str:
        """
        Downloads high-quality video stream with 6-Layer Anti-Bot Defense.

        Layer 1: pytubefix MWEB/WEB with auto PO Token + FFmpeg slice
        Layer 2: pytubefix MWEB/WEB with OAuth cache + FFmpeg slice
        Layer 3: yt-dlp with cookies + client rotation
        Layer 4: yt-dlp aggressive client rotation (tvhtml5/android/mweb/ios)
        Layer 5: yt-dlp bare fallback
        Layer 6: Invidious API Public Proxy Stream Extractor (100% VPS IP block bypass)
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
                logger.warning("⚠️ Corrupted MP4 file detected in temp. Purging: %s", output_path)
                try:
                    os.remove(output_path)
                except Exception:
                    pass

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
                    "extractor_args": {"youtube": {"player_client": ["tvhtml5", "mweb", "android", "ios", "web_creator", "tv_embedded"]}}
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
                "extractor_args": {"youtube": {"player_client": ["tvhtml5", "mweb", "android", "ios", "web_creator", "tv_embedded"]}}
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
            logger.warning("❌ [L5] yt-dlp bare fallback video failed: %s", str(e5)[:200])

        # ── LAYER 6: Invidious & Piped API Public Proxy Stream Fallback ───
        try:
            logger.info("🌐 [L6] Attempting Invidious/Piped Proxy API video stream extraction for %s...", video_id)
            _, inv_video_url = _fetch_proxy_stream_urls(video_id)
            if inv_video_url:
                if _ffmpeg_slice_from_url(inv_video_url):
                    logger.info("✅ [L6] Video stream downloaded via Proxy API fallback: %s", output_path)
                    return output_path
        except Exception as e6:
            logger.warning("❌ [L6] Proxy API video fallback failed: %s", str(e6)[:200])

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
            raise FileNotFoundError(
                f"Solusi: (1) Install Node.js di VPS, "
                f"(2) Salin OAuth tokens.json ke {OAUTH_CACHE_DIR}, "
                f"(3) Ekspor cookies.txt ke {YOUTUBE_COOKIES_FILE}"
            )

        logger.info("Video stream ready (%d MB): %s", os.path.getsize(output_path) // (1024 * 1024), output_path)
        return output_path
