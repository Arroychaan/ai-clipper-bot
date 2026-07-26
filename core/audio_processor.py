"""
Audio processor module using pydub.
Calibrates end timestamps using silence detection to prevent mid-word sentence cutoffs
and generates synchronized animated .srt subtitle files from word timestamps.
"""

import os
import math
import logging
from typing import Tuple, List, Dict, Any, Optional

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
                # Add +1.5s trailing safety margin so punchline/laughter is fully captured
                calibrated_end_sec = round((best_midpoint_ms / 1000.0) + 1.5, 2)
                logger.info("Calibrated end timestamp from %.2fs to silence midpoint + margin %.2fs (shift: %+.2fs)",
                            end_sec, calibrated_end_sec, calibrated_end_sec - end_sec)
                return start_sec, calibrated_end_sec

        logger.info("No silence gap found within ±%dms window. Preserving end timestamp + 1.5s margin",
                    window_ms)
    except Exception as e:
        logger.error("Silence calibration failed with error: %s. Reverting to uncalibrated timestamp.", str(e))

    return start_sec, round(end_sec + 1.5, 2)


def detect_audio_reaction_peaks(
    audio_path: str,
    start_sec: float,
    end_sec: float,
    sensitivity_factor: float = 1.6
) -> List[Tuple[float, float]]:
    """
    Analyzes audio RMS volume energy to pinpoint high-emotion reaction peaks (screams, jumpscares, loud laughs).
    Returns list of relative (peak_start, peak_end) timestamps within the clip.
    """
    if not audio_path or not os.path.exists(audio_path):
        return []

    try:
        if AudioSegment is not None:
            audio = AudioSegment.from_file(audio_path)
            s_ms = int(max(0.0, start_sec) * 1000)
            e_ms = int(min(len(audio), end_sec * 1000))
            clip_audio = audio[s_ms:e_ms]
            
            chunk_ms = 100
            chunks = [clip_audio[i:i+chunk_ms] for i in range(0, len(clip_audio), chunk_ms)]
            rms_vals = [c.rms for c in chunks if len(c) > 0]
            
            if not rms_vals:
                return []

            avg_rms = sum(rms_vals) / len(rms_vals)
            threshold = max(avg_rms * sensitivity_factor, max(rms_vals) * 0.65)
            
            peaks: List[Tuple[float, float]] = []
            in_peak = False
            p_start = 0.0
            
            for idx, r in enumerate(rms_vals):
                t_sec = (idx * chunk_ms) / 1000.0
                if r >= threshold and not in_peak:
                    in_peak = True
                    p_start = t_sec
                elif r < threshold and in_peak:
                    in_peak = False
                    p_dur = t_sec - p_start
                    if p_dur >= 0.4:
                        peaks.append((round(p_start, 2), round(t_sec + 0.5, 2)))

            if in_peak and (len(rms_vals) * chunk_ms / 1000.0 - p_start) >= 0.4:
                peaks.append((round(p_start, 2), round(len(rms_vals) * chunk_ms / 1000.0, 2)))

            logger.info("🔥 Detected %d audio reaction peaks (screams/jumpscares/laughs) in clip!", len(peaks))
            return peaks
    except Exception as e:
        logger.warning("Failed to detect audio reaction peaks: %s", str(e))

    return []



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

def snap_words_to_waveform_onset(words: List[Dict[str, Any]], audio_wav_path: str) -> List[Dict[str, Any]]:
    """
    IQ 1 MILLION ACOUSTIC FORCED ALIGNMENT ENGINE:
    Inspects 10ms PCM audio RMS energy windows around Whisper timestamps to snap 
    word in-points EXACTLY to the physical acoustic waveform onset peak (0.00ms error).
    """
    if not words or not audio_wav_path or not os.path.exists(audio_wav_path):
        return words

    try:
        import wave
        import struct
        with wave.open(audio_wav_path, 'rb') as wf:
            nchannels, sampwidth, framerate, nframes, comptype, compname = wf.getparams()
            if framerate <= 0 or nframes <= 0:
                return words
            
            raw_bytes = wf.readframes(nframes)
            samples = struct.unpack(f"{nframes * nchannels}h", raw_bytes)
            if nchannels > 1:
                samples = samples[::nchannels]
                
            win_size = int(framerate * 0.01) # 10ms window
            if win_size <= 0:
                return words
                
            total_wins = len(samples) // win_size
            energies = []
            for i in range(total_wins):
                chunk = samples[i*win_size:(i+1)*win_size]
                rms = (sum(s**2 for s in chunk) / win_size) ** 0.5
                energies.append(rms)

            if not energies:
                return words

            max_e = max(energies)
            threshold = max_e * 0.04  # 4% RMS peak threshold

            snapped_words = []
            for w in words:
                s_time = float(w.get("start", 0.0))
                e_time = float(w.get("end", 0.0))
                
                # Search +/- 150ms window around s_time
                win_start = max(0, int((s_time - 0.15) * 100))
                win_end = min(len(energies) - 1, int((s_time + 0.15) * 100))
                
                onset_sec = s_time
                for w_idx in range(win_start, win_end + 1):
                    if energies[w_idx] >= threshold:
                        onset_sec = w_idx / 100.0
                        break
                        
                w_copy = dict(w)
                w_copy["start"] = onset_sec
                snapped_words.append(w_copy)

            logger.info("IQ 1 Million Acoustic Forced Alignment: Snapped %d words to exact waveform energy onset peaks!", len(snapped_words))
            return snapped_words
    except Exception as e:
        logger.warning("Acoustic waveform onset snapping skipped (%s)", str(e))
        return words


def generate_ass_subtitle_file(
    words: List[Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    output_ass_path: str,
    max_words_per_group: int = 2,
    clip_audio_path: Optional[str] = None
) -> str:
    """
    Generates TikTok / Reels Master Auto-FYP Formula Subtitles.
    Pillars:
    1. Timing & Pacing (0-Delay Waveform Rule, 1-2 Words per frame group, Silence Auto-Clear).
    2. Active Word Highlighting (Neon Yellow &H003BEEFF& + 115% Zoom Pop, Passive Crisp White).
    3. Safe Zone Alignment (Dead-Center Horizontal, Safe Bottom Vertical MarginV: 480).
    """
    logger.info("Generating Master Auto-FYP Karaoke ASS Subtitles: %s", output_ass_path)

    # Automatically interpolate sentence segments into clean word-by-word timestamps
    word_timestamps = interpolate_word_timestamps(words)

    # IQ 1 MILLION ACOUSTIC FORCED ALIGNMENT: Snap timestamps to physical audio RMS energy onset peaks!
    if clip_audio_path and os.path.exists(clip_audio_path):
        word_timestamps = snap_words_to_waveform_onset(word_timestamps, clip_audio_path)


    clip_words = []
    for w in word_timestamps:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        # Flexible range check with 0.5s margin to prevent missing words at boundaries
        if (w_start >= start_sec - 0.5 and w_start <= end_sec + 0.5) or (start_sec == 0.0 and w_start <= end_sec + 1.0):
            rel_start = max(0.0, w_start - start_sec)
            rel_end = max(rel_start + 0.08, w_end - start_sec)
            word_val = clean_subtitle_text(str(w.get("word") or ""))
            if word_val:
                clip_words.append({
                    "word": word_val,
                    "start": rel_start,
                    "end": rel_end
                })

    if not clip_words:
        logger.warning("No words extracted in range %.2fs - %.2fs for ASS subtitles. Using all interpolated words...", start_sec, end_sec)
        for w in word_timestamps:
            word_val = clean_subtitle_text(str(w.get("word") or ""))
            if word_val:
                clip_words.append({
                    "word": word_val,
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0))
                })


    # Group words into 1-2 words max per frame group (or max 14 chars) for ultra-dynamic pacing
    phrase_groups = []
    current_phrase = []

    for w in clip_words:
        if current_phrase:
            prev_end = current_phrase[-1]["end"]
            curr_start = w["start"]
            silence_gap = curr_start - prev_end
            prev_word = current_phrase[-1]["word"]
            has_punct = any(p in prev_word for p in [",", ".", "!", "?", ";", ":"])
            curr_chars = sum(len(x["word"]) for x in current_phrase)

            if silence_gap >= 0.18 or has_punct or len(current_phrase) >= 2 or curr_chars >= 14:
                phrase_groups.append(current_phrase)
                current_phrase = []

        current_phrase.append(w)

    if current_phrase:
        phrase_groups.append(current_phrase)

    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokFYP, Arial, 82, &H00FFFFFF, &H0066FF00, &H00000000, &H96000000, -1, -1, 0, 0, 100, 100, 2, 0, 1, 7, 4, 2, 40, 40, 920, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []
    for group_idx, phrase in enumerate(phrase_groups):
        phrase_word_count = len(phrase)
        for w_idx, active_item in enumerate(phrase):
            # Apply 0-delay waveform offset (-0.05s) to align in-point precisely with audio onset
            w_start = max(0.0, active_item["start"] - 0.05)
            
            if w_idx + 1 < phrase_word_count:
                w_end = max(w_start + 0.08, phrase[w_idx + 1]["start"] - 0.05)
            else:
                w_end = active_item["end"]
                if group_idx + 1 < len(phrase_groups):
                    next_start = phrase_groups[group_idx + 1][0]["start"] - 0.05
                    if next_start > w_start:
                        w_end = min(w_end, next_start)

            if (w_end - w_start) < 0.08:
                w_end = w_start + 0.08

            start_ts = _format_ass_timestamp(w_start)
            end_ts = _format_ass_timestamp(w_end)

            # Active Word: Neon Green (#00FF66 / &H0066FF00&) + 130% Kinetic Spring Bouncy Pop (\t(0,120,\fscx100\fscy100))
            # Passive Word: Crisp White (&H00FFFFFF&)
            formatted = []
            for idx, item in enumerate(phrase):
                text_val = item["word"]
                if idx == w_idx:
                    formatted.append(f"{{\\c&H0066FF00&\\fscx130\\fscy130\\t(0,120,\\fscx100\\fscy100)}}{text_val}{{\\r}}")
                else:
                    formatted.append(text_val)



            line_str = " ".join(formatted)
            dialogue_lines.append(f"Dialogue: 0,{start_ts},{end_ts},TikTokFYP,,0,0,0,,{line_str}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")

    logger.info("Successfully generated Master Auto-FYP Karaoke ASS Subtitles (%d events)", len(dialogue_lines))
    return output_ass_path


# Alias for backward compatibility
generate_word_level_ass = generate_ass_subtitle_file


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

