"""
Groq Vision AI Multimodal Frame Analyzer.

Extracts keyframes from video using FFmpeg, sends them to Groq Vision API
(qwen/qwen3.6-27b) for visual analysis of facial expressions, emotions,
gameplay context, and engagement scoring.

This replaces the blind text-only clip selection with true Video Understanding AI.

Cloud-only processing: 0 MB local RAM for the AI inference.
"""

import os
import base64
import logging
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from config import TEMP_DIR

logger = logging.getLogger(__name__)


@dataclass
class KeyframeAnalysis:
    """Analysis result for a single keyframe."""
    timestamp_sec: float
    frame_path: str
    engagement_score: float  # 0-100
    description: str
    has_facecam_reaction: bool
    emotion: str  # 'neutral', 'excited', 'scared', 'laughing', 'angry'
    gameplay_intensity: str  # 'low', 'medium', 'high', 'climax'


def extract_keyframes(
    video_path: str,
    output_dir: Optional[str] = None,
    interval_sec: float = 3.0,
    max_frames: int = 30,
    quality: int = 2,
) -> List[Tuple[float, str]]:
    """
    Extracts keyframes from a video file at regular intervals using FFmpeg.

    Args:
        video_path: Path to the input video.
        output_dir: Directory to save keyframe JPEGs. Defaults to TEMP_DIR.
        interval_sec: Interval between keyframes in seconds (default 3.0s).
        max_frames: Maximum number of keyframes to extract (default 30).
        quality: JPEG quality (2 = high quality, 5 = medium, 10 = low).

    Returns:
        List of (timestamp_sec, frame_path) tuples.
    """
    if not os.path.exists(video_path):
        logger.warning("Video file does not exist for keyframe extraction: %s", video_path)
        return []

    out_dir = output_dir or str(TEMP_DIR)
    os.makedirs(out_dir, exist_ok=True)

    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    pattern = os.path.join(out_dir, f"kf_{video_basename}_%04d.jpg")

    # Use FFmpeg to extract frames at the specified interval
    # fps=1/interval gives us one frame every interval_sec seconds
    fps_val = 1.0 / max(0.5, interval_sec)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps={fps_val:.4f},scale=640:-1",
        "-frames:v", str(max_frames),
        "-q:v", str(quality),
        "-threads", "1",
        pattern
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=120
        )
    except subprocess.TimeoutExpired:
        logger.warning("Keyframe extraction timed out after 120s.")
    except subprocess.CalledProcessError as e:
        logger.warning("Keyframe extraction failed: %s", e.stderr[-300:] if e.stderr else str(e))
    except Exception as e:
        logger.warning("Keyframe extraction error: %s", str(e))

    # Collect extracted frames and map to timestamps
    frames: List[Tuple[float, str]] = []
    for i in range(1, max_frames + 1):
        frame_path = os.path.join(out_dir, f"kf_{video_basename}_{i:04d}.jpg")
        if os.path.exists(frame_path) and os.path.getsize(frame_path) > 1000:
            timestamp = (i - 1) * interval_sec
            frames.append((round(timestamp, 2), frame_path))

    logger.info(
        "📸 Extracted %d keyframes from %s (interval=%.1fs)",
        len(frames), os.path.basename(video_path), interval_sec
    )
    return frames


def _encode_image_base64(image_path: str) -> str:
    """Reads an image file and returns its base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze_keyframes_with_vision(
    keyframes: List[Tuple[float, str]],
    groq_client: Any,
    batch_size: int = 4,
    context_hint: str = "Indonesian gaming streamer (Windah Basudara style) playing games with facecam overlay"
) -> List[KeyframeAnalysis]:
    """
    Sends keyframes to Groq Vision API (qwen/qwen3.6-27b) for multimodal analysis.

    Analyzes facial expressions, emotions, gameplay context, and engagement potential
    of each keyframe. Processes in batches of up to 4 images per API request.

    Args:
        keyframes: List of (timestamp_sec, frame_path) tuples.
        groq_client: ResilientGroqClient instance.
        batch_size: Number of frames per API request (max 4 due to 5-image limit with margin).
        context_hint: Description of the video content type.

    Returns:
        List of KeyframeAnalysis results.
    """
    if not keyframes:
        return []

    results: List[KeyframeAnalysis] = []

    # Process in batches
    for batch_start in range(0, len(keyframes), batch_size):
        batch = keyframes[batch_start:batch_start + batch_size]

        # Build multimodal message content
        content_parts = []
        timestamp_labels = []

        for idx, (ts, frame_path) in enumerate(batch):
            label = f"Frame {idx+1} (t={ts:.1f}s)"
            timestamp_labels.append((ts, frame_path, label))

            try:
                img_b64 = _encode_image_base64(frame_path)
                content_parts.append({
                    "type": "text",
                    "text": label
                })
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                })
            except Exception as e:
                logger.warning("Failed to encode frame %s: %s", frame_path, str(e))
                continue

        if not content_parts:
            continue

        # Add analysis instruction
        content_parts.append({
            "type": "text",
            "text": f"""Analyze each frame from this {context_hint} video.

For EACH frame, evaluate:
1. engagement_score (0-100): How viral/engaging is this moment visually?
2. emotion: What emotion is the streamer showing? (neutral/excited/scared/laughing/angry)
3. has_facecam_reaction: Is the streamer visibly reacting? (true/false)
4. gameplay_intensity: How intense is the gameplay? (low/medium/high/climax)
5. description: One-sentence description of what's happening.

Respond as JSON array:
[{{"frame": 1, "timestamp": 0.0, "engagement_score": 85, "emotion": "excited", "has_facecam_reaction": true, "gameplay_intensity": "high", "description": "Streamer screaming after clutch kill"}}]"""
        })

        try:
            import json

            def _call_vision(client: Any) -> Any:
                return client.chat.completions.create(
                    model="qwen/qwen3.6-27b",
                    messages=[{
                        "role": "user",
                        "content": content_parts
                    }],
                    temperature=0.2,
                    max_tokens=2000
                )

            completion = groq_client.execute_with_retry(_call_vision)
            raw_response = completion.choices[0].message.content.strip()

            # Parse JSON response (handle markdown code blocks)
            if "```json" in raw_response:
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_response:
                raw_response = raw_response.split("```")[1].split("```")[0].strip()

            # Handle /think tags from qwen if present
            if "</think>" in raw_response:
                raw_response = raw_response.split("</think>")[-1].strip()

            frame_analyses = json.loads(raw_response)

            for fa in frame_analyses:
                frame_idx = int(fa.get("frame", 1)) - 1
                if 0 <= frame_idx < len(batch):
                    ts, fp, _ = timestamp_labels[frame_idx]
                    results.append(KeyframeAnalysis(
                        timestamp_sec=ts,
                        frame_path=fp,
                        engagement_score=float(fa.get("engagement_score", 50)),
                        description=str(fa.get("description", "")),
                        has_facecam_reaction=bool(fa.get("has_facecam_reaction", False)),
                        emotion=str(fa.get("emotion", "neutral")),
                        gameplay_intensity=str(fa.get("gameplay_intensity", "medium"))
                    ))

            logger.info(
                "🧠 Vision AI analyzed batch of %d frames (scores: %s)",
                len(batch),
                [f"{r.engagement_score:.0f}" for r in results[-len(batch):]]
            )

        except Exception as e:
            logger.warning("Vision AI analysis failed for batch: %s", str(e)[:200])
            # Fallback: create neutral analysis for unprocessed frames
            for ts, fp, _ in timestamp_labels:
                results.append(KeyframeAnalysis(
                    timestamp_sec=ts,
                    frame_path=fp,
                    engagement_score=50.0,
                    description="Vision analysis unavailable",
                    has_facecam_reaction=False,
                    emotion="neutral",
                    gameplay_intensity="medium"
                ))

    logger.info(
        "🧠 Groq Vision AI completed: %d keyframes analyzed, avg engagement=%.1f",
        len(results),
        sum(r.engagement_score for r in results) / max(1, len(results))
    )
    return results


def find_highlight_windows(
    vision_results: List[KeyframeAnalysis],
    min_duration_sec: float = 60.0,
    max_duration_sec: float = 90.0,
    frame_interval_sec: float = 3.0
) -> List[Dict[str, Any]]:
    """
    Identifies the best highlight windows from vision analysis results.

    Scans through keyframe scores using a sliding window to find the contiguous
    segment with the highest average engagement.

    Args:
        vision_results: List of KeyframeAnalysis from Vision AI.
        min_duration_sec: Minimum clip duration.
        max_duration_sec: Maximum clip duration.
        frame_interval_sec: Time between keyframes.

    Returns:
        List of highlight windows sorted by score (highest first).
        Each dict contains: start_sec, end_sec, avg_score, peak_score, has_reactions.
    """
    if not vision_results:
        return []

    sorted_results = sorted(vision_results, key=lambda r: r.timestamp_sec)

    # Sliding window
    min_frames = max(1, int(min_duration_sec / frame_interval_sec))
    max_frames = max(min_frames, int(max_duration_sec / frame_interval_sec))

    windows: List[Dict[str, Any]] = []

    for window_size in range(min_frames, max_frames + 1):
        for start_idx in range(len(sorted_results) - window_size + 1):
            window = sorted_results[start_idx:start_idx + window_size]

            scores = [r.engagement_score for r in window]
            avg_score = sum(scores) / len(scores)
            peak_score = max(scores)
            reaction_count = sum(1 for r in window if r.has_facecam_reaction)
            climax_count = sum(1 for r in window if r.gameplay_intensity == "climax")

            # Composite score: avg engagement + bonus for reactions and climax
            composite = avg_score + (reaction_count * 3.0) + (climax_count * 5.0)

            windows.append({
                "start_sec": window[0].timestamp_sec,
                "end_sec": window[-1].timestamp_sec + frame_interval_sec,
                "avg_score": round(avg_score, 1),
                "peak_score": round(peak_score, 1),
                "composite_score": round(composite, 1),
                "reaction_count": reaction_count,
                "climax_count": climax_count,
                "frame_count": len(window)
            })

    # Sort by composite score descending and deduplicate overlapping windows
    windows.sort(key=lambda w: w["composite_score"], reverse=True)

    # Remove overlapping windows (keep best non-overlapping)
    selected: List[Dict[str, Any]] = []
    for w in windows:
        overlap = False
        for s in selected:
            if not (w["end_sec"] <= s["start_sec"] or w["start_sec"] >= s["end_sec"]):
                overlap = True
                break
        if not overlap:
            selected.append(w)
            if len(selected) >= 10:  # Max 10 candidate highlights
                break

    logger.info(
        "🎯 Vision AI identified %d non-overlapping highlight windows (top score: %.1f)",
        len(selected),
        selected[0]["composite_score"] if selected else 0
    )
    return selected


def cleanup_keyframes(keyframes: List[Tuple[float, str]]) -> None:
    """Removes all extracted keyframe JPEG files from disk."""
    for _, frame_path in keyframes:
        try:
            if os.path.exists(frame_path):
                os.remove(frame_path)
        except Exception:
            pass
    logger.info("🧹 Cleaned up %d keyframe files", len(keyframes))
