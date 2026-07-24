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
        
        # Final attempt after all backoffs exhausted
        try:
            return api_func(self.client, *args, **kwargs)
        except Exception as e:
            logger.error("All Groq API retries exhausted. Final error: %s", str(e))
            raise e

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribes audio file using Groq Whisper Large v3 with word-level timestamps.
        
        Args:
            audio_path: Path to the audio file (.wav format).
            
        Returns:
            Dict containing transcription text and word-level timestamp list.
        """
        logger.info("Transcribing audio file via Groq Whisper v3: %s", audio_path)

        def _call_whisper(client: Groq) -> Any:
            with open(audio_path, "rb") as audio_file:
                return client.audio.transcriptions.create(
                    file=(audio_path, audio_file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    timestamp_granularities=["word"]
                )

        response = self.execute_with_retry(_call_whisper)
        
        # Convert response to standard dict
        if hasattr(response, "model_dump"):
            res_dict = response.model_dump()
        elif isinstance(response, dict):
            res_dict = response
        else:
            res_dict = json.loads(response.text)

        logger.info("Audio transcription completed successfully (%d words extracted)",
                    len(res_dict.get("words", [])))
        return res_dict

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

        system_prompt = f"""You are an elite viral content producer specializing in TikTok, IG Reels, and YouTube Shorts.
Your task is to analyze the speech transcript and select the SINGLE MOST VIRAL segment with high emotional hook and retention.

STRICT REQUIREMENTS:
1. Duration MUST be between {MIN_CLIP_DURATION} and {MAX_CLIP_DURATION} seconds.
2. Calculate a 'viral_score' (integer 1-100) evaluating hook strength, curiosity gap, emotional peak, and punchline. Only assign >90 for genuinely elite viral moments.
3. Generate 'title': A short, clickbait viral title (under 60 chars) {lang_instruction}.
4. Generate 'caption': A SHORT, MINIMALIST 1-2 line aesthetic caption {lang_instruction} that engages viewers to comment.
5. Generate 'hashtags': An array of 4-6 hot trending hashtags suitable for TikTok & Shorts (e.g., ["#fyp", "#viral", "#shorts", "#trending", "#mindset"]).
6. Output MUST be strictly valid JSON matching this format:
{{
  "viral_score": 95,
  "start_time": 120.5,
  "end_time": 155.0,
  "title": "Viral Clickbait Title",
  "caption": "Short minimalist caption line.",
  "hashtags": ["#fyp", "#viral", "#shorts", "#trending"]
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
