"""
Audio processor module using pydub.
Calibrates end timestamps using silence detection to prevent mid-word sentence cutoffs
and generates synchronized animated .srt subtitle files from word timestamps.
"""

import os
import math
import logging
from typing import Tuple, List, Dict, Any

try:
    from pydub import AudioSegment  # type: ignore
    from pydub.silence import detect_silence  # type: ignore
except ImportError:
    AudioSegment = None  # type: ignore
    detect_silence = None  # type: ignore

logger = logging.getLogger(__name__)


def calibrate_cut_timestamps(
    audio_path: str,
    start_sec: float,
    end_sec: float,
    window_ms: int = 3000,
    min_silence_len: int = 150,
    silence_thresh: int = -38
) -> Tuple[float, float]:
    """
    Adjusts end_sec to the exact midpoint of the nearest silent gap around end_sec.
    Prevents clip boundaries from cutting off mid-word.
    
    Args:
        audio_path: Path to the WAV audio file.
        start_sec: Initial clip start timestamp in seconds.
        end_sec: Initial clip end timestamp in seconds.
        window_ms: Search window around end_sec (default ±3000ms).
        min_silence_len: Minimum duration of silence in ms (default 150ms).
        silence_thresh: Silence threshold in dBFS (default -38dBFS).
        
    Returns:
        Tuple[float, float]: (start_sec, calibrated_end_sec).
    """
    logger.info("Calibrating cut end timestamp around %.2fs using pydub silence detection...", end_sec)

    if AudioSegment is None or detect_silence is None:
        logger.warning("pydub library is not installed. Skipping silence calibration.")
        return start_sec, end_sec

    try:
        audio = AudioSegment.from_file(audio_path)
        total_len_ms = len(audio)
        
        target_end_ms = int(end_sec * 1000)
        search_start_ms = max(0, target_end_ms - window_ms)
        search_end_ms = min(total_len_ms, target_end_ms + window_ms)
        
        chunk = audio[search_start_ms:search_end_ms]
        
        # Detect silent gaps in the search chunk
        silences = detect_silence(
            chunk,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )

        if silences:
            # Find silence gap whose midpoint is closest to target_end_ms
            best_midpoint_ms = None
            min_distance = float("inf")
            
            for s_start, s_end in silences:
                abs_start = search_start_ms + s_start
                abs_end = search_start_ms + s_end
                midpoint = (abs_start + abs_end) / 2.0
                dist = abs(midpoint - target_end_ms)
                
                if dist < min_distance:
                    min_distance = dist
                    best_midpoint_ms = midpoint
            
            if best_midpoint_ms is not None:
                calibrated_end_sec = round(best_midpoint_ms / 1000.0, 2)
                logger.info("Calibrated end timestamp from %.2fs to silence midpoint %.2fs (shift: %+.2fs)",
                            end_sec, calibrated_end_sec, calibrated_end_sec - end_sec)
                return start_sec, calibrated_end_sec

        logger.info("No silence gap found within ±%dms window. Preserving end timestamp %.2fs",
                    window_ms, end_sec)
    except Exception as e:
        logger.error("Silence calibration failed with error: %s. Reverting to uncalibrated timestamp.", str(e))

    return start_sec, end_sec


def _format_srt_timestamp(seconds: float) -> str:
    """Formats floating-point seconds into SRT timestamp format: HH:MM:SS,mmm"""
    total_ms = int(max(0.0, seconds) * 1000)
    hours = total_ms // (3600 * 1000)
    total_ms %= (3600 * 1000)
    minutes = total_ms // (60 * 1000)
    total_ms %= (60 * 1000)
    secs = total_ms // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_subtitle_file(
    words: List[Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    output_srt_path: str,
    max_words_per_group: int = 3
) -> str:
    """
    Generates a synchronized SRT subtitle file from Whisper word-level timestamps.
    Normalizes timestamps to begin at 00:00:00 for the trimmed video clip.
    
    Args:
        words: List of word dicts containing 'word', 'start', and 'end'.
        start_sec: Start time of video clip.
        end_sec: End time of video clip.
        output_srt_path: Output filepath for generated .srt file.
        max_words_per_group: Maximum words per displayed subtitle chunk (default 3 for short video punchiness).
        
    Returns:
        str: Path to the generated .srt file.
    """
    logger.info("Generating subtitle file at: %s", output_srt_path)

    # Filter words strictly falling within the clip duration
    clip_words = []
    for w in words:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        if w_start >= start_sec and w_end <= end_sec:
            # Shift timestamps relative to clip start
            rel_start = max(0.0, w_start - start_sec)
            rel_end = max(rel_start + 0.1, w_end - start_sec)
            word_val = str(w.get("word") or w.get("text") or "").strip().upper()
            if word_val:
                clip_words.append({
                    "word": word_val,
                    "start": rel_start,
                    "end": rel_end
                })

    # Group words into short 2-3 word high-retention subtitle groups
    sub_entries = []
    current_group = []
    
    for word_info in clip_words:
        current_group.append(word_info)
        if len(current_group) >= max_words_per_group:
            sub_entries.append(current_group)
            current_group = []
            
    if current_group:
        sub_entries.append(current_group)

    # Build SRT file content
    srt_lines = []
    for idx, group in enumerate(sub_entries, start=1):
        group_text = " ".join(item["word"] for item in group)
        group_start = group[0]["start"]
        group_end = group[-1]["end"]
        
        # Ensure minimum subtitle display duration (300ms) for readability
        if (group_end - group_start) < 0.3:
            group_end = group_start + 0.3
            
        start_str = _format_srt_timestamp(group_start)
        end_str = _format_srt_timestamp(group_end)
        
        srt_lines.append(f"{idx}")
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(f"{group_text}\n")

    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))

    logger.info("Successfully generated SRT subtitle file (%d blocks created)", len(sub_entries))
    return output_srt_path
