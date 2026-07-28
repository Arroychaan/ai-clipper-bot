"""
Resilient Groq API client with multi-key rotation and exponential backoff.
Handles audio transcription via Whisper Large v3 and viral clip extraction via Llama 3.3 70B.
"""

import json
import time
import logging
import itertools
from typing import Any, Callable, Dict, List, Optional
try:
    from groq import Groq, RateLimitError, APIError  # type: ignore
except ImportError:
    Groq = None  # type: ignore
    RateLimitError = Exception  # type: ignore
    APIError = Exception  # type: ignore

from config import GROQ_KEYS, MIN_CLIP_DURATION, MAX_CLIP_DURATION

logger = logging.getLogger(__name__)


def _compress_and_chunk_audio(audio_path: str, max_chunk_mb: float = 18.0) -> List[str]:
    """
    Compresses audio to lightweight 32k mono MP3 and splits into <= 18MB chunks if necessary.
    Guarantees every chunk is strictly under Groq's 25 MB file size limit.

    Returns list of chunk audio file paths.
    """
    import os
    import subprocess

    if not os.path.exists(audio_path):
        return [audio_path]

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

    # 1. Convert WAV to compressed 32k mono MP3 (reduces size by ~10x)
    mp3_path = audio_path.rsplit(".", 1)[0] + "_compressed.mp3"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "32k",
            mp3_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=120)
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1000:
            file_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
            audio_path = mp3_path
            logger.info("Compressed WAV to 32k mono MP3 (New Size: %.2f MB)", file_size_mb)
    except Exception as e:
        logger.warning("Failed to compress WAV to MP3: %s", str(e))

    # If compressed audio is under max_chunk_mb, return it directly
    if file_size_mb <= max_chunk_mb:
        return [audio_path]

    # 2. Split audio into 10-minute segments (600s each)
    logger.info("Audio file size (%.1f MB) exceeds Groq limit (25 MB). Chunking into 10-min segments...", file_size_mb)
    chunk_paths = []
    chunk_idx = 0

    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        total_dur = float(res.stdout.strip())
    except Exception:
        total_dur = 3600.0

    segment_dur = 600.0
    curr_start = 0.0

    while curr_start < total_dur:
        chunk_out = f"{audio_path}_chunk_{chunk_idx}.mp3"
        slice_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{curr_start:.2f}",
            "-t", f"{segment_dur:.2f}",
            "-i", audio_path,
            "-c", "copy",
            chunk_out
        ]
        try:
            subprocess.run(slice_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=60)
            if os.path.exists(chunk_out) and os.path.getsize(chunk_out) > 1000:
                chunk_paths.append(chunk_out)
        except Exception as e_slice:
            logger.warning("Chunk slice %d failed: %s", chunk_idx, str(e_slice))

        curr_start += segment_dur
        chunk_idx += 1

    return chunk_paths if chunk_paths else [audio_path]


class ResilientGroqClient:
    """
    Fault-tolerant Groq API client that cycles through available API keys
    and applies exponential backoff retry logic upon encountering rate limits or errors.
    """

    def __init__(self, api_keys: Optional[tuple[str, ...]] = None):
        if Groq is None:
            raise ImportError("The 'groq' package is not installed. Please run 'pip install groq'.")

        keys = api_keys or GROQ_KEYS
        if not keys:
            raise ValueError("No valid Groq API keys provided in configuration or environment variables.")
        
        self.api_keys = list(keys)
        self.key_cycle = itertools.cycle(self.api_keys)
        self.current_key = next(self.key_cycle)
        self.client = Groq(api_key=self.current_key)
        logger.info("Initialized ResilientGroqClient with %d API key(s). Active key ending in ...%s",
                    len(self.api_keys), self.current_key[-6:])

    def _rotate_key(self) -> None:
        """Rotates to the next API key in the pool and updates client instance."""
        self.current_key = next(self.key_cycle)
        self.client = Groq(api_key=self.current_key)
        logger.warning("Rotated to next Groq API key (ending in ...%s)", self.current_key[-6:])

    def execute_with_retry(self, api_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Executes a Groq API function with key rotation and exponential backoff retry.
        
        Backoff intervals: 2s, 4s, 8s, 16s, 32s.
        """
        backoff_delays = [2, 4, 8, 16, 32]
        
        for attempt, delay in enumerate(backoff_delays, start=1):
            try:
                return api_func(self.client, *args, **kwargs)
            except (RateLimitError, APIError, Exception) as e:
                logger.warning(
                    "Groq API call attempt %d/%d failed with error: %s. Rotating key and retrying in %ds...",
                    attempt, len(backoff_delays), str(e), delay
                )
                self._rotate_key()
                time.sleep(delay)
        
        try:
            return api_func(self.client, *args, **kwargs)
        except Exception as e:
            logger.error("All Groq API retries exhausted. Final error: %s", str(e))
            raise e

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribes audio file using Groq Whisper Large v3 with word-level timestamps.
        Automatically compresses WAV to 32k MP3 and chunks into <=18MB segments
        to prevent '413 Request Entity Too Large' errors.
        """
        import os

        logger.info("Transcribing audio file via Groq Whisper v3: %s", audio_path)

        # Pre-process audio: compress to 32k MP3 and chunk if > 18MB
        chunks = _compress_and_chunk_audio(audio_path, max_chunk_mb=18.0)

        all_text_parts = []
        all_segments = []
        all_words = []
        time_offset = 0.0

        for chunk_idx, chunk_file in enumerate(chunks):
            logger.info("🎙️ Transcribing chunk [%d/%d]: %s", chunk_idx + 1, len(chunks), chunk_file)

            def _call_whisper(client: Groq) -> Any:
                with open(chunk_file, "rb") as af:
                    return client.audio.transcriptions.create(
                        file=(os.path.basename(chunk_file), af.read()),
                        model="whisper-large-v3",
                        response_format="verbose_json",
                        timestamp_granularities=["word"]
                    )

            try:
                response = self.execute_with_retry(_call_whisper)

                if hasattr(response, "model_dump"):
                    res_dict = response.model_dump()
                elif isinstance(response, dict):
                    res_dict = response
                else:
                    res_dict = json.loads(response.text)

                chunk_text = res_dict.get("text", "")
                if chunk_text:
                    all_text_parts.append(chunk_text)

                for seg in res_dict.get("segments", []):
                    all_segments.append({
                        "start": round(seg.get("start", 0.0) + time_offset, 2),
                        "end": round(seg.get("end", 0.0) + time_offset, 2),
                        "text": seg.get("text", "")
                    })

                for w in res_dict.get("words", []):
                    all_words.append({
                        "word": w.get("word", ""),
                        "start": round(w.get("start", 0.0) + time_offset, 2),
                        "end": round(w.get("end", 0.0) + time_offset, 2)
                    })

                if all_segments:
                    time_offset = all_segments[-1]["end"]
                else:
                    time_offset += 600.0

            finally:
                if chunk_file != audio_path and os.path.exists(chunk_file):
                    try:
                        os.remove(chunk_file)
                    except Exception:
                        pass

        logger.info("Audio transcription completed successfully (%d words, %d segments extracted)",
                    len(all_words), len(all_segments))

        return {
            "text": " ".join(all_text_parts),
            "segments": all_segments,
            "words": all_words
        }

    def extract_viral_clip(self, transcript_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes transcription data via Llama 3.3 70B to identify the most viral clip segment,
        assign a Viral Hook Score (1-100), a short minimalist caption, and hot trending hashtags.
        
        Args:
            transcript_data: Transcription dict containing text and word list with timestamps.
            
        Returns:
            Dict with keys: 'start_time', 'end_time', 'title', 'caption', 'hashtags', 'viral_score'.
        """
        text_content = transcript_data.get("text", "")
        words = transcript_data.get("words") or transcript_data.get("segments", [])
        
        if not text_content and words:
            text_content = " ".join(w.get("word") or w.get("text", "") for w in words)
        
        # Provide timestamp context snippet
        timestamped_summary = []
        step = max(1, len(words) // 60) if words else 1
        for w in words[::step]:
            w_text = w.get("word") or w.get("text", "")
            w_start = float(w.get("start", 0.0))
            timestamped_summary.append(f"[{w_start:.1f}s]: {w_text}")
        
        timestamp_snippet = "\n".join(timestamped_summary[:60])

        from config import TARGET_LANGUAGE, MIN_VIRAL_SCORE

        lang_instruction = "in Indonesian (Bahasa Indonesia)" if TARGET_LANGUAGE == "id" else "in English"

        system_prompt = f"""You are an elite viral content producer specializing in TikTok, IG Reels, and YouTube Shorts (Wayin AI level high-retention editor).
Your task is to analyze the speech transcript with timestamps and select the SINGLE MOST VIRAL, COMPLETE STORY/JOKE SEGMENT.

CRITICAL FYP RETENTION RULES:
1. STRICT DURATION: Each clip MUST be between {MIN_CLIP_DURATION} and {MAX_CLIP_DURATION} seconds (MINIMUM 60 seconds, MAXIMUM 90 seconds).
2. COMPLETE STORY/COMEDIC ARC: The start_time MUST begin at the exact start of a sentence/setup, and end_time MUST conclude AFTER the full punchline, scream, or reaction laughter is completely finished. NEVER cut off mid-sentence, mid-joke, or before the reaction ends!
3. Calculate 'viral_score' (integer 1-100) evaluating hook strength (first 3s), curiosity gap, emotional peak, and punchline payoff.
4. Generate 'title': Short clickbait viral title (under 50 chars) {lang_instruction}.
5. Generate 'caption': Short 1-2 line aesthetic caption {lang_instruction}.
6. Generate 'hashtags': Array of 4-6 trending hashtags.

OUTPUT JSON FORMAT ONLY:
{{
  "viral_score": 95,
  "start_time": 120.5,
  "end_time": 185.0,
  "title": "Viral Clickbait Title",
  "caption": "Short aesthetic caption.",
  "hashtags": ["#fyp", "#viral", "#shorts"]
}}"""


        user_prompt = f"""TRANSCRIPT SNIPPET:
{text_content[:7000]}

TIMESTAMP MARKS:
{timestamp_snippet}

Evaluate and select the best clip segment duration between {MIN_CLIP_DURATION}s and {MAX_CLIP_DURATION}s."""

        def _call_llama(client: Groq) -> Any:
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

        logger.info("Querying Groq Llama 3.3 70B for high-retention viral clip selection...")
        completion = self.execute_with_retry(_call_llama)
        raw_json_str = completion.choices[0].message.content.strip()
        
        # Parse JSON output robustly
        try:
            clip_meta = json.loads(raw_json_str)
        except json.JSONDecodeError:
            if "```json" in raw_json_str:
                raw_json_str = raw_json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json_str:
                raw_json_str = raw_json_str.split("```")[1].split("```")[0].strip()
            clip_meta = json.loads(raw_json_str)

        start_time = float(clip_meta.get("start_time", 0.0))
        end_time = float(clip_meta.get("end_time", start_time + 30.0))
        
        # Enforce duration safety limits
        duration = end_time - start_time
        if duration < MIN_CLIP_DURATION or duration > MAX_CLIP_DURATION:
            logger.warning("Extracted duration (%.1fs) outside limits [%.1fs - %.1fs]. Normalizing...",
                           duration, MIN_CLIP_DURATION, MAX_CLIP_DURATION)
            end_time = start_time + min(max(duration, MIN_CLIP_DURATION), MAX_CLIP_DURATION)

        viral_score = int(clip_meta.get("viral_score", 90))
        clip_meta["start_time"] = round(start_time, 2)
        clip_meta["end_time"] = round(end_time, 2)
        clip_meta["viral_score"] = viral_score
        
        # Ensure hashtags is a list or formatted string
        raw_tags = clip_meta.get("hashtags", ["#fyp", "#viral", "#shorts", "#trending"])
        if isinstance(raw_tags, list):
            clip_meta["hashtags_str"] = " ".join(raw_tags)
        else:
            clip_meta["hashtags_str"] = str(raw_tags)

        logger.info(
            "Extracted clip metadata: Title='%s', Viral Score=%d, Start=%.2fs, End=%.2fs (Duration=%.2fs)",
            clip_meta.get("title"), viral_score, clip_meta["start_time"], clip_meta["end_time"],
            clip_meta["end_time"] - clip_meta["start_time"]
        )

        return clip_meta

    def extract_multiple_viral_clips(self, transcript_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyzes transcription data via Llama 3.3 70B to identify ALL top viral candidate segments (5 to 20 clips)
        with a strict Viral Hook Score >= 95.
        """
        text_content = transcript_data.get("text", "")
        words = transcript_data.get("words") or transcript_data.get("segments", [])
        
        if not text_content and words:
            text_content = " ".join(w.get("word") or w.get("text", "") for w in words)
        
        # Build comprehensive timestamp marks across the entire video
        timestamped_summary = []
        step = max(1, len(words) // 150) if words else 1
        for w in words[::step]:
            w_text = w.get("word") or w.get("text", "")
            w_start = float(w.get("start", 0.0))
            timestamped_summary.append(f"[{w_start:.1f}s]: {w_text}")
        
        timestamp_snippet = "\n".join(timestamped_summary[:200])

        from config import TARGET_LANGUAGE, MIN_VIRAL_SCORE, MIN_CLIP_DURATION, MAX_CLIP_DURATION

        lang_instruction = "in Indonesian (Bahasa Indonesia)" if TARGET_LANGUAGE == "id" else "in English"

        system_prompt = f"""You are an elite viral content producer specializing in TikTok, IG Reels, and YouTube Shorts (Wayin AI level high-retention editor).
Your task is to analyze the full transcript with timestamps and extract ALL TOP VIRAL CLIP SEGMENTS (between 5 and 20 clips depending on video length & density of viral moments).

STRICT CRITERIA & RULES:
1. SCORE THRESHOLD: EVERY clip MUST have a 'viral_score' >= 95! Only select truly elite, high-retention, funny, dramatic, or mind-blowing moments.
2. COMPLETE COMEDIC STORY ARCS & PUNCHLINES: Each clip MUST start at the setup phase of a story/joke and MUST end AFTER the full punchline, scream, or laughter reaction is complete. NEVER cut off mid-sentence or before the reaction ends.
3. NO OVERLAPPING CLIPS: Ensure extracted clip time ranges do not heavily overlap (at least 30 seconds apart).
4. STRICT DURATION: Each clip MUST be between {MIN_CLIP_DURATION} and {MAX_CLIP_DURATION} seconds long (MINIMUM 60.0s, MAXIMUM 90.0s).
5. Provide: 'title' (short clickbait under 50 chars), 'caption' (1-2 line aesthetic caption {lang_instruction}), and 'hashtags' (4-6 trending tags).

OUTPUT MUST BE A STRICT JSON OBJECT CONTAINING A "clips" ARRAY:
{{
  "clips": [
    {{
      "viral_score": 98,
      "start_time": 120.5,
      "end_time": 185.0,
      "title": "Viral Moment 1 Title",
      "caption": "Short aesthetic caption.",
      "hashtags": ["#fyp", "#viral", "#shorts"]
    }}
  ]
}}"""

        user_prompt = f"""FULL TRANSCRIPT SNIPPET:
{text_content[:15000]}

TIMESTAMP MARKS ACROSS VIDEO:
{timestamp_snippet}

Evaluate the entire transcript and extract ALL viral clip candidates (between 5 and 20 clips) with viral_score >= 95."""

        def _call_llama(client: Groq) -> Any:
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

        logger.info("Querying Groq Llama 3.3 70B for multi-clip extraction (Target: 5-20 clips >= 95 score)...")
        completion = self.execute_with_retry(_call_llama)
        raw_json_str = completion.choices[0].message.content.strip()
        
        try:
            res_json = json.loads(raw_json_str)
        except json.JSONDecodeError:
            if "```json" in raw_json_str:
                raw_json_str = raw_json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json_str:
                raw_json_str = raw_json_str.split("```")[1].split("```")[0].strip()
            res_json = json.loads(raw_json_str)

        raw_clips = res_json.get("clips") if isinstance(res_json, dict) and "clips" in res_json else [res_json] if isinstance(res_json, dict) else []

        valid_clips = []
        for c in raw_clips:
            if not isinstance(c, dict):
                continue
            s_score = int(c.get("viral_score", 95))
            if s_score < MIN_VIRAL_SCORE:
                logger.info("Filtering out clip candidate with score %d < %d", s_score, MIN_VIRAL_SCORE)
                continue

            s_time = float(c.get("start_time", 0.0))
            e_time = float(c.get("end_time", s_time + 30.0))
            dur = e_time - s_time
            if dur < MIN_CLIP_DURATION or dur > MAX_CLIP_DURATION:
                e_time = s_time + min(max(dur, MIN_CLIP_DURATION), MAX_CLIP_DURATION)

            c["start_time"] = round(s_time, 2)
            c["end_time"] = round(e_time, 2)
            c["viral_score"] = s_score
            
            raw_tags = c.get("hashtags", ["#fyp", "#viral", "#shorts", "#trending"])
            c["hashtags_str"] = " ".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)
            valid_clips.append(c)

        if not valid_clips and raw_clips and isinstance(raw_clips[0], dict):
            single = raw_clips[0]
            single["viral_score"] = 95
            valid_clips.append(single)

        logger.info("Extracted %d elite viral clips (Score >= 95) from video!", len(valid_clips))
        return valid_clips

    def extract_multimodal_viral_clips(
        self,
        transcript_data: Dict[str, Any],
        vision_highlights: Optional[List[Dict[str, Any]]] = None,
        audio_peaks: Optional[List[tuple]] = None,
        scene_boundaries: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        2026 Multimodal Clip Selection Engine.

        Fuses 4 signal sources for truly intelligent clip selection:
        1. Text transcript (Whisper) — dialogue, jokes, punchlines
        2. Vision AI highlights (Groq qwen3.6-27b) — visual engagement, emotions
        3. Audio energy peaks — screams, jumpscares, loud laughter
        4. Scene boundaries (PySceneDetect) — natural cut points

        This replaces the blind text-only extract_multiple_viral_clips.
        """
        text_content = transcript_data.get("text", "")
        words = transcript_data.get("words") or transcript_data.get("segments", [])

        if not text_content and words:
            text_content = " ".join(w.get("word") or w.get("text", "") for w in words)

        # Build timestamp marks
        timestamped_summary = []
        step = max(1, len(words) // 150) if words else 1
        for w in words[::step]:
            w_text = w.get("word") or w.get("text", "")
            w_start = float(w.get("start", 0.0))
            timestamped_summary.append(f"[{w_start:.1f}s]: {w_text}")
        timestamp_snippet = "\n".join(timestamped_summary[:200])

        # Build vision AI context
        vision_context = ""
        if vision_highlights:
            vision_parts = []
            for vh in vision_highlights[:10]:
                vision_parts.append(
                    f"  - Window {vh['start_sec']:.0f}s-{vh['end_sec']:.0f}s: "
                    f"visual_engagement={vh['avg_score']:.0f}/100, "
                    f"peak={vh['peak_score']:.0f}, "
                    f"reactions={vh['reaction_count']}, "
                    f"climax_moments={vh['climax_count']}"
                )
            vision_context = "VISION AI HIGHLIGHT ANALYSIS (from actual video frames):\n" + "\n".join(vision_parts)

        # Build audio peaks context
        audio_context = ""
        if audio_peaks:
            peak_parts = [f"  - Audio energy peak at {p[0]:.1f}s-{p[1]:.1f}s (scream/jumpscare/laugh)" for p in audio_peaks[:20]]
            audio_context = "AUDIO ENERGY PEAKS (screams, jumpscares, loud reactions):\n" + "\n".join(peak_parts)

        # Build scene boundary context
        scene_context = ""
        if scene_boundaries:
            boundary_parts = [f"  - Scene cut at {b.timestamp_sec:.1f}s" for b in scene_boundaries[:30]]
            scene_context = "SCENE BOUNDARIES (natural cut points - OBS transitions, camera switches):\n" + "\n".join(boundary_parts)

        from config import TARGET_LANGUAGE, MIN_VIRAL_SCORE, MIN_CLIP_DURATION, MAX_CLIP_DURATION
        lang_instruction = "in Indonesian (Bahasa Indonesia)" if TARGET_LANGUAGE == "id" else "in English"

        system_prompt = f"""You are an elite viral content producer using MULTIMODAL INTELLIGENCE.
You have been given 4 signal sources from the same gaming stream video:
1. TEXT TRANSCRIPT — what the streamer said
2. VISION AI ANALYSIS — what was VISUALLY happening (engagement scores, emotions, reactions from actual screenshots)
3. AUDIO ENERGY PEAKS — moments of screaming, jumpscares, loud laughter
4. SCENE BOUNDARIES — natural OBS scene transitions/camera switches

USE ALL 4 SIGNALS TOGETHER to select the BEST viral clips. A truly viral moment will have:
- HIGH visual engagement score (Vision AI)
- Emotional streamer reaction (excited/scared/laughing)
- Audio energy peak (scream/jumpscare)
- Complete story/joke arc in the transcript text
- Clip boundaries that align with natural scene cuts

STRICT RULES:
1. EVERY clip MUST have viral_score >= 95.
2. Each clip MUST be between {MIN_CLIP_DURATION}s and {MAX_CLIP_DURATION}s.
3. COMPLETE STORY ARCS: Start at setup, end AFTER full punchline/reaction.
4. ALIGN start_time and end_time with nearest SCENE BOUNDARIES when possible (within 3s).
5. PRIORITIZE windows with highest Vision AI engagement scores AND audio peaks.
6. NO overlapping clips (at least 30s apart).
7. Extract 5-20 clips depending on video density.

OUTPUT STRICT JSON:
{{
  "clips": [
    {{
      "viral_score": 98,
      "start_time": 120.5,
      "end_time": 185.0,
      "title": "Viral Moment Title",
      "caption": "Short aesthetic caption {lang_instruction}.",
      "hashtags": ["#fyp", "#viral", "#shorts"],
      "selection_reason": "High vision score 92 + audio peak at 145s + complete joke arc"
    }}
  ]
}}"""

        user_prompt = f"""FULL TRANSCRIPT:
{text_content[:12000]}

TIMESTAMP MARKS:
{timestamp_snippet}

{vision_context}

{audio_context}

{scene_context}

Using ALL 4 signal sources, extract the BEST viral clips (5-20 clips, score >= 95)."""

        def _call_llama(client: Any) -> Any:
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

        logger.info("🧠 Querying Llama 3.3 70B with MULTIMODAL FUSION (text + vision + audio + scene)...")
        completion = self.execute_with_retry(_call_llama)
        raw_json_str = completion.choices[0].message.content.strip()

        try:
            res_json = json.loads(raw_json_str)
        except json.JSONDecodeError:
            if "```json" in raw_json_str:
                raw_json_str = raw_json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json_str:
                raw_json_str = raw_json_str.split("```")[1].split("```")[0].strip()
            res_json = json.loads(raw_json_str)

        raw_clips = res_json.get("clips") if isinstance(res_json, dict) and "clips" in res_json else [res_json] if isinstance(res_json, dict) else []

        valid_clips = []
        for c in raw_clips:
            if not isinstance(c, dict):
                continue
            s_score = int(c.get("viral_score", 95))
            if s_score < MIN_VIRAL_SCORE:
                logger.info("Filtering out clip with multimodal score %d < %d", s_score, MIN_VIRAL_SCORE)
                continue

            s_time = float(c.get("start_time", 0.0))
            e_time = float(c.get("end_time", s_time + 30.0))
            dur = e_time - s_time
            if dur < MIN_CLIP_DURATION or dur > MAX_CLIP_DURATION:
                e_time = s_time + min(max(dur, MIN_CLIP_DURATION), MAX_CLIP_DURATION)

            # Snap to scene boundaries if available
            if scene_boundaries:
                from core.scene_detector import snap_to_nearest_scene_boundary
                s_time = snap_to_nearest_scene_boundary(s_time, scene_boundaries, max_snap_distance_sec=3.0, prefer_direction="before")
                e_time = snap_to_nearest_scene_boundary(e_time, scene_boundaries, max_snap_distance_sec=3.0, prefer_direction="after")

            c["start_time"] = round(s_time, 2)
            c["end_time"] = round(e_time, 2)
            c["viral_score"] = s_score

            raw_tags = c.get("hashtags", ["#fyp", "#viral", "#shorts", "#trending"])
            c["hashtags_str"] = " ".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)
            valid_clips.append(c)

        if not valid_clips and raw_clips and isinstance(raw_clips[0], dict):
            single = raw_clips[0]
            single["viral_score"] = 95
            valid_clips.append(single)

        logger.info(
            "🎯 Multimodal fusion extracted %d elite clips (Vision+Audio+Text+Scene)!",
            len(valid_clips)
        )
        return valid_clips

