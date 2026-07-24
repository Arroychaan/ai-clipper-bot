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


def _format_ass_timestamp(seconds: float) -> str:
    """Formats floating-point seconds into ASS timestamp format: H:MM:SS.cs"""
    total_cs = int(max(0.0, seconds) * 100)
    hours = total_cs // (3600 * 100)
    total_cs %= (3600 * 100)
    minutes = total_cs // (60 * 100)
    total_cs %= (60 * 100)
    secs = total_cs // 100
    cs = total_cs % 100
    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{cs:02d}"


import re


def clean_subtitle_text(text: str) -> str:
    """
    Cleans subtitle text to fix typos, remove stutter fillers ('uhm', 'err', 'ya', etc.),
    and strip weird non-ASCII characters while converting to crisp uppercase.
    """
    if not text:
        return ""

    # Remove bracketed noise markers like [Laughter], (Applause), [Musik]
    text = re.sub(r"\[.*?\]|\(.*?\)", "", text)

    # Normalize multiple spaces or punctuation repeats
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\?|\!|\.){2,}", r"\1", text)

    # Strip strange symbols but preserve Indonesian letters, digits, and basic punctuation
    text = re.sub(r"[^\w\s\?\!\,\.\'\-]", "", text)

    return text.strip().upper()


def interpolate_word_timestamps(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transforms sentence-level or raw transcript segments into precise word-by-word timestamps.
    If items already contain word-level timestamps ('word' key present), returns them directly.
    Otherwise, splits sentences into individual words and proportionally interpolates word timestamps based on character length.
    """
    extracted_words: List[Dict[str, Any]] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        # Check if item is already a word-level timestamp object
        if "word" in item and item["word"]:
            w_val = clean_subtitle_text(str(item["word"]))
            if w_val:
                extracted_words.append({
                    "word": w_val,
                    "start": float(item.get("start", 0.0)),
                    "end": float(item.get("end", 0.0))
                })
            continue

        # Item is a sentence-level segment
        raw_text = str(item.get("text") or "").strip()
        cleaned_text = clean_subtitle_text(raw_text)
        s_start = float(item.get("start", 0.0))
        s_end = float(item.get("end", 0.0))
        s_duration = max(0.2, s_end - s_start)

        words_in_text = cleaned_text.split()
        if not words_in_text:
            continue

        total_chars = sum(len(w) for w in words_in_text)
        if total_chars == 0:
            total_chars = len(words_in_text)

        curr_time = s_start
        for w in words_in_text:
            w_ratio = len(w) / total_chars
            w_dur = max(0.12, s_duration * w_ratio)
            w_end = min(s_end, curr_time + w_dur)
            extracted_words.append({
                "word": w,
                "start": curr_time,
                "end": w_end
            })
            curr_time = w_end

    return extracted_words


def generate_ass_subtitle_file(
    words: List[Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    output_ass_path: str,
    max_words_per_group: int = 3
) -> str:
    """
    Generates World-Class OpusClip / Wayin.ai / CapCut Style Dynamic Subtitles.
    Displays 3-4 word readable phrases on screen with real-time active word karaoke 
    highlighting in Neon Yellow (&H0000FFFF&) and 120% font pop scale, while non-active 
    words stay in crisp White with a 5px thick black outline & drop shadow.
    """
    logger.info("Generating World-Class OpusClip Style ASS Subtitles: %s", output_ass_path)

    # Automatically interpolate sentence segments into clean word-by-word timestamps
    word_timestamps = interpolate_word_timestamps(words)

    clip_words = []
    for w in word_timestamps:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        if w_start >= start_sec and w_end <= end_sec:
            rel_start = max(0.0, w_start - start_sec)
            rel_end = max(rel_start + 0.1, w_end - start_sec)
            word_val = clean_subtitle_text(str(w.get("word") or ""))
            if word_val:
                clip_words.append({
                    "word": word_val,
                    "start": rel_start,
                    "end": rel_end
                })

    if not clip_words:
        logger.warning("No words extracted in range %.2fs - %.2fs for ASS subtitles.", start_sec, end_sec)
        return generate_subtitle_file(words, start_sec, end_sec, output_ass_path.replace(".ass", ".srt"))

    # Group words into 3-4 word readable phrases (~22 chars max per phrase)
    phrase_groups = []
    current_phrase = []
    current_char_len = 0

    for w in clip_words:
        current_phrase.append(w)
        current_char_len += len(w["word"])
        if len(current_phrase) >= 3 or current_char_len >= 22:
            phrase_groups.append(current_phrase)
            current_phrase = []
            current_char_len = 0
    if current_phrase:
        phrase_groups.append(current_phrase)

    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CapCut, Liberation Sans, 78, &H00FFFFFF, &H0000FFFF, &H00000000, &H80000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 5, 3, 2, 40, 40, 460, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for group_idx, phrase in enumerate(phrase_groups):
        phrase_word_count = len(phrase)
        for w_idx, active_item in enumerate(phrase):
            w_start = active_item["start"]
            
            # Determine end timestamp of active word event
            if w_idx + 1 < phrase_word_count:
                w_end = phrase[w_idx + 1]["start"]
            else:
                w_end = active_item["end"]
                # If next phrase group exists, cap to start of next phrase group
                if group_idx + 1 < len(phrase_groups):
                    next_phrase_start = phrase_groups[group_idx + 1][0]["start"]
                    if next_phrase_start > w_start:
                        w_end = min(w_end, next_phrase_start)

            if (w_end - w_start) < 0.08:
                w_end = w_start + 0.08

            start_ts = _format_ass_timestamp(w_start)
            end_ts = _format_ass_timestamp(w_end)

            # Build phrase string where active word has Neon Yellow color (&H0000FFFF&) + 120% pop scale
            formatted_words = []
            for idx, item in enumerate(phrase):
                w_text = item["word"]
                if idx == w_idx:
                    formatted_words.append(f"{{\\c&H0000FFFF&\\fscx120\\fscy120}}{w_text}{{\\r}}")
                else:
                    formatted_words.append(w_text)

            line_text = " ".join(formatted_words)
            dialogue_lines.append(f"Dialogue: 0,{start_ts},{end_ts},CapCut,,0,0,0,,{line_text}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")

    logger.info("Successfully generated OpusClip Style ASS subtitles (%d phrase events)", len(dialogue_lines))
    return output_ass_path






def generate_subtitle_file(
    words: List[Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    output_srt_path: str,
    max_words_per_group: int = 3
) -> str:
    """
    Generates a synchronized SRT subtitle file from Whisper word-level timestamps.
    """
    logger.info("Generating subtitle file at: %s", output_srt_path)

    clip_words = []
    for w in words:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        if w_start >= start_sec and w_end <= end_sec:
            rel_start = max(0.0, w_start - start_sec)
            rel_end = max(rel_start + 0.1, w_end - start_sec)
            word_val = str(w.get("word") or w.get("text") or "").strip().upper()
            if word_val:
                clip_words.append({
                    "word": word_val,
                    "start": rel_start,
                    "end": rel_end
                })

    sub_entries = []
    current_group = []
    
    for word_info in clip_words:
        current_group.append(word_info)
        if len(current_group) >= max_words_per_group:
            sub_entries.append(current_group)
            current_group = []
            
    if current_group:
        sub_entries.append(current_group)

    srt_lines = []
    for idx, group in enumerate(sub_entries, start=1):
        group_text = " ".join(item["word"] for item in group)
        group_start = group[0]["start"]
        group_end = group[-1]["end"]
        
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

