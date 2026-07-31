"""
24/7 Automated Video Clipping and Publishing Engine for ai-clipper-bot.
Runs an infinite fault-tolerant loop on Linux, executing feed fetching, AI transcription,
Llama clip selection, audio silence calibration, vertical FFmpeg rendering, and multi-platform publishing.
"""

import os
import sys
import time
import glob
import shutil
import logging
import traceback as tb_module
from typing import List, Dict, Any, Optional

from config import (
    LOG_FILE_PATH,
    TEMP_DIR,
    CLIPS_DIR,
    MIN_VIRAL_SCORE,
    RAMPUP_MODE,
    RAMPUP_INTERVAL_SEC,
    STANDARD_INTERVAL_SEC,
    RETRY_DELAY_SEC,
    SOURCE_FEED_URL,
    GAMING_MODE,
    PODCAST_FEEDS,
    MINIMUM_FREE_DISK_GB
)
from core.db_manager import init_db, is_processed, mark_status, save_clip, get_setting, get_unprocessed_custom_candidates
from core.groq_manager import ResilientGroqClient

from core.fetcher import YouTubeFetcher
from core.audio_processor import calibrate_cut_timestamps, generate_ass_subtitle_file, generate_subtitle_file
from core.ffmpeg_renderer import render_vertical_shorts, render_gaming_split_shorts
from core.facecam_detector import detect_streamer_facecam



# Configure production logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ai-clipper-bot")


def cleanup_temp_workspace() -> None:
    """
    ATOMIC CLEANUP: Explicitly purges all temporary working files (.mp4, .wav, .srt, .ass)
    from TEMP_DIR to guarantee zero disk growth and zero memory leaks.
    """
    logger.info("Executing atomic workspace cleanup in: %s", TEMP_DIR)
    patterns = ["*.mp4", "*.wav", "*.srt", "*.ass", "*.webm", "*.mkv"]
    for pattern in patterns:
        search_path = os.path.join(TEMP_DIR, pattern)
        for filepath in glob.glob(search_path):
            try:
                os.remove(filepath)
                logger.info("Cleaned up temp file: %s", filepath)
            except Exception as e:
                logger.warning("Failed to remove temp file '%s': %s", filepath, str(e))


def ensure_disk_space(path: Optional[str] = None, minimum_gb: float = 2.0) -> None:
    """Verifies that the VPS has at least minimum_gb free disk space before proceeding."""
    check_path = path or str(TEMP_DIR)
    try:
        total, used, free = shutil.disk_usage(check_path)
        free_gb = free / (1024 ** 3)
        total_gb = total / (1024 ** 3)
        logger.info("💾 Disk space: %.1f GB free / %.1f GB total", free_gb, total_gb)
        if free_gb < minimum_gb:
            raise RuntimeError(f"Ruang disk tersisa {free_gb:.1f} GB; minimum yang diperlukan {minimum_gb:.1f} GB.")
    except Exception as e:
        if "Ruang disk tersisa" in str(e):
            raise e
        logger.warning("Could not check disk space: %s", str(e))


def process_single_video(
    video_item: Dict[str, str],
    groq_client: ResilientGroqClient,
    force_gaming_mode: bool = False
) -> bool:
    """
    2026 Multimodal Clipping Pipeline.

    10-Step Pipeline:
    1. Initialize & disk check
    2. Fetch transcript (YouTube captions or Groq Whisper)
    3. Download video stream
    4. Extract keyframes (FFmpeg → JPEG)
    5. Scene detection (PySceneDetect)
    6. Vision AI analysis (Groq qwen3.6-27b)
    7. Audio energy peak detection
    8. Multimodal clip selection (Llama 3.3 70B + Vision + Audio + Scene fusion)
    9. Dynamic facecam tracking (YuNet + EMA smoothing)
    10. Render 1080x1920 split-screen (CRF 18, lanczos, color grading)

    Guarantees atomic file cleanup using try...finally.
    """
    video_id = video_item.get("id") or video_item.get("video_id") or ""
    video_url = video_item["url"]
    video_title = video_item.get("title", "YouTube Video")

    ensure_disk_space(str(TEMP_DIR), MINIMUM_FREE_DISK_GB)

    logger.info("==================================================")
    from core.db_manager import add_system_log

    logger.info("Processing Candidate Video: %s (%s)", video_title, video_url)
    logger.info("==================================================")

    # STEP 1: Initialize
    msg_start = f"Inisialisasi pemrosesan klip instan untuk video '{video_title}' ({video_id})"
    logger.info("👉 [STEP 1/10] %s", msg_start)
    add_system_log(video_id, "INFO", "[STEP 1/10]", msg_start)
    mark_status(video_id, "PROCESSING")

    audio_path = None
    video_path = None

    try:
        # STEP 2: Get video transcript
        msg_trans = "Mengambil transkrip/subtitel YouTube..."
        logger.info("👉 [STEP 2/10] %s", msg_trans)
        transcript_data = YouTubeFetcher.fetch_transcript(video_id)

        audio_path = None
        if not transcript_data:
            msg_whisper = "Transkrip tidak tersedia. Mengunduh audio & menggunakan Groq Whisper Large v3..."
            logger.info("👉 %s", msg_whisper)
            add_system_log(video_id, "INFO", "[STEP 2/10]", msg_whisper)
            try:
                _, audio_path = YouTubeFetcher.download_audio(video_url)
                transcript_data = groq_client.transcribe_audio(audio_path)
            except Exception as audio_err:
                tb_audio = tb_module.format_exc()
                err_msg = f"Gagal mengunduh/transkrip audio: {str(audio_err)}"
                logger.warning(err_msg)
                add_system_log(video_id, "ERROR", "[STEP 2/10]", err_msg, tb_audio)
                return False

        # STEP 3: Download video stream (full or sliced)
        msg_dl = "Mengunduh aliran video untuk analisis visual..."
        logger.info("👉 [STEP 3/10] %s", msg_dl)
        add_system_log(video_id, "INFO", "[STEP 3/10]", msg_dl)
        video_path = YouTubeFetcher.download_video_stream(video_url)

        from core.fetcher import is_valid_mp4_video
        if not is_valid_mp4_video(video_path):
            logger.warning("⚠️ Corrupted video stream. Re-downloading...")
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            video_path = YouTubeFetcher.download_video_stream(video_url)

        # STEP 4: Extract keyframes for Vision AI
        msg_kf = "Mengekstrak keyframe untuk analisis Vision AI..."
        logger.info("👉 [STEP 4/10] %s", msg_kf)
        add_system_log(video_id, "INFO", "[STEP 4/10]", msg_kf)

        from core.vision_analyzer import extract_keyframes, analyze_keyframes_with_vision, find_highlight_windows, cleanup_keyframes
        keyframes = extract_keyframes(video_path, interval_sec=3.0, max_frames=30)

        # STEP 5: Scene detection
        msg_scene = "Mendeteksi batas scene (OBS transitions, camera switches)..."
        logger.info("👉 [STEP 5/10] %s", msg_scene)
        add_system_log(video_id, "INFO", "[STEP 5/10]", msg_scene)

        from core.scene_detector import detect_scene_boundaries
        scene_boundaries = detect_scene_boundaries(video_path)

        # STEP 6: Vision AI analysis
        msg_vision = "Menganalisis keyframe via Groq Vision AI (qwen3.6-27b)..."
        logger.info("👉 [STEP 6/10] %s", msg_vision)
        add_system_log(video_id, "INFO", "[STEP 6/10]", msg_vision)

        vision_results = []
        vision_highlights = []
        try:
            vision_results = analyze_keyframes_with_vision(keyframes, groq_client)
            vision_highlights = find_highlight_windows(vision_results)
        except Exception as vision_err:
            logger.warning("Vision AI analysis failed (falling back to text-only): %s", str(vision_err)[:200])

        # Cleanup keyframe files immediately after analysis
        cleanup_keyframes(keyframes)

        # STEP 7: Audio energy peak detection
        msg_audio = "Mendeteksi audio energy peaks (screams, jumpscares, laughter)..."
        logger.info("👉 [STEP 7/10] %s", msg_audio)
        add_system_log(video_id, "INFO", "[STEP 7/10]", msg_audio)

        from core.audio_processor import detect_audio_reaction_peaks
        if not (audio_path and os.path.exists(audio_path)):
            try:
                _, audio_path = YouTubeFetcher.download_audio(video_url)
            except Exception:
                pass

        # Get total duration for full-video audio analysis
        full_audio_peaks = []
        if audio_path and os.path.exists(audio_path):
            try:
                from pydub import AudioSegment  # type: ignore
                audio_seg = AudioSegment.from_file(audio_path)
                total_audio_dur = len(audio_seg) / 1000.0
                full_audio_peaks = detect_audio_reaction_peaks(audio_path, 0.0, total_audio_dur)
            except Exception as ap_err:
                logger.warning("Full audio peak detection failed: %s", str(ap_err)[:100])

        # STEP 8: Multimodal clip selection
        msg_ai = "🧠 Menjalankan Multimodal Fusion Clip Selection (Teks + Vision + Audio + Scene)..."
        logger.info("👉 [STEP 8/10] %s", msg_ai)
        add_system_log(video_id, "INFO", "[STEP 8/10]", msg_ai)

        # Use multimodal extraction if vision data is available, otherwise fall back to text-only
        if vision_highlights or full_audio_peaks or scene_boundaries:
            viral_clips = groq_client.extract_multimodal_viral_clips(
                transcript_data,
                vision_highlights=vision_highlights,
                audio_peaks=full_audio_peaks,
                scene_boundaries=scene_boundaries
            )
        else:
            logger.info("No multimodal signals available. Falling back to text-only extraction.")
            viral_clips = groq_client.extract_multiple_viral_clips(transcript_data)

        if not viral_clips:
            warn_msg = f"Tidak ditemukan kandidat klip dengan skor viral >= {MIN_VIRAL_SCORE}. Melewati render."
            logger.warning(warn_msg)
            add_system_log(video_id, "WARNING", "[STEP 8/10]", warn_msg)
            mark_status(video_id, "COMPLETED")
            return True

        total_extracted = len(viral_clips)
        msg_summary = f"🎉 Terdeteksi {total_extracted} klip viral kelas atas (Multimodal Fusion)! Memulai batch rendering..."
        logger.info(msg_summary)
        add_system_log(video_id, "INFO", "[STEP 8/10]", msg_summary)

        # Batch render each clip
        rendered_count = 0
        for clip_idx, clip_meta in enumerate(viral_clips, start=1):
            raw_start = clip_meta["start_time"]
            raw_end = clip_meta["end_time"]
            v_score = clip_meta.get("viral_score", 95)
            title = clip_meta.get("title", f"Viral Clip {clip_idx}")
            caption = clip_meta.get("caption", title)
            hashtags_str = clip_meta.get("hashtags_str", "#fyp #viral #shorts #trending")

            # STEP 9: Calibrate cut timestamps + Dynamic facecam tracking
            msg_calib = f"[{clip_idx}/{total_extracted}] Mengalibrasi waktu potong & tracking facecam '{title}'..."
            logger.info("👉 [STEP 9/10] %s", msg_calib)
            add_system_log(video_id, "INFO", "[STEP 9/10]", msg_calib)

            if audio_path and os.path.exists(audio_path):
                start_sec, end_sec = calibrate_cut_timestamps(audio_path, raw_start, raw_end)
            else:
                start_sec, end_sec = max(0.0, float(raw_start)), float(raw_end)
            duration = end_sec - start_sec

            # Dynamic facecam tracking for this clip's time range
            dynamic_keyframes = None
            if force_gaming_mode:
                from core.facecam_detector import detect_dynamic_facecam_track
                clip_sample_times = [round(start_sec + i * (duration / 10), 1) for i in range(10)]
                dynamic_keyframes = detect_dynamic_facecam_track(
                    video_path,
                    sample_timestamps_sec=clip_sample_times,
                    ema_alpha=0.35
                )

            # Audio peaks for this specific clip range
            r_peaks = detect_audio_reaction_peaks(audio_path, start_sec, end_sec) if (audio_path and os.path.exists(audio_path)) else None

            # Pre-render disk check
            try:
                _, _, free_bytes = shutil.disk_usage(str(CLIPS_DIR))
                free_mb = free_bytes / (1024 * 1024)
                if free_mb < 200:
                    warn_disk = f"⚠️ Disk space sangat rendah ({free_mb:.0f} MB). Skip render klip {clip_idx}."
                    logger.warning(warn_disk)
                    add_system_log(video_id, "WARNING", "[STEP 10/10]", warn_disk)
                    continue
            except Exception:
                pass

            # Pre-render facecam check: Auto-detect if video has a streamer facecam (Windah Basudara style)
            facecam_coords = detect_streamer_facecam(video_path)
            has_facecam = facecam_coords.get("detected", False)
            current_active_mode = get_setting("active_mode", "WINDAH").upper().strip()
            use_gaming_render = force_gaming_mode or has_facecam or (current_active_mode == "WINDAH")

            # STEP 10: Render
            clip_filename = f"clip_{video_id}_{int(start_sec)}.mp4"
            output_clip_path = str(CLIPS_DIR / clip_filename)

            from core.ffmpeg_renderer import MediaInput
            media_input = MediaInput(path=video_path, is_presliced=False, source_start=start_sec)

            try:
                if use_gaming_render:
                    msg_render = f"🎮 [{clip_idx}/{total_extracted}] Merender Gaming Split-Screen 2026 (Skor {v_score}) -> {clip_filename}..."
                    logger.info("👉 [STEP 10/10] %s", msg_render)
                    add_system_log(video_id, "INFO", "[STEP 10/10]", msg_render)

                    render_success = render_gaming_split_shorts(
                        input_video=media_input,
                        start_time=start_sec,
                        duration=duration,
                        output_path=output_clip_path,
                        facecam_coords=facecam_coords,
                        subtitle_path=None,
                        hook_title=title,
                        reaction_peaks=r_peaks,
                        dynamic_crop_keyframes=dynamic_keyframes
                    )
                else:
                    msg_render = f"🎙️ [{clip_idx}/{total_extracted}] Merender Podcast Split-Screen 2026 (Skor {v_score}) -> {clip_filename}..."
                    logger.info("👉 [STEP 10/10] %s", msg_render)
                    add_system_log(video_id, "INFO", "[STEP 10/10]", msg_render)
                    render_success = render_vertical_shorts(
                        input_video=media_input,
                        start_time=start_sec,
                        duration=duration,
                        output_path=output_clip_path,
                        subtitle_path=None
                    )

                if render_success and os.path.exists(output_clip_path) and os.path.getsize(output_clip_path) >= 50000:
                    clip_id = f"{video_id}_{int(start_sec)}"
                    clip_size_mb = os.path.getsize(output_clip_path) / (1024 * 1024)
                    save_clip(
                        clip_id=clip_id,
                        video_id=video_id,
                        video_title=video_url,
                        clip_title=title,
                        caption=caption,
                        hashtags=hashtags_str,
                        viral_score=v_score,
                        duration=duration,
                        clip_path=clip_filename
                    )
                    rendered_count += 1
                    reason = clip_meta.get("selection_reason", "multimodal fusion")
                    add_system_log(video_id, "INFO", "[STEP 10/10]",
                                   f"🎉 Klip [{clip_idx}/{total_extracted}] '{title}' (Skor {v_score}, {clip_size_mb:.1f} MB) berhasil! Alasan: {reason}")
                else:
                    file_exists = os.path.exists(output_clip_path)
                    file_size = os.path.getsize(output_clip_path) if file_exists else 0
                    err_reason = f"render_success={render_success}, file_exists={file_exists}, file_size={file_size} bytes"
                    logger.error("❌ Render output invalid for clip %d: %s", clip_idx, err_reason)
                    add_system_log(video_id, "ERROR", "[STEP 10/10]",
                                   f"❌ Render klip {clip_idx} GAGAL! Detail: {err_reason}. Cek log FFmpeg di atas untuk error spesifik.")
                    # Cleanup failed output file
                    if file_exists and file_size < 50000:
                        try:
                            os.remove(output_clip_path)
                        except Exception:
                            pass
            except Exception as render_err:
                tb_render = tb_module.format_exc()
                logger.error("❌ Render EXCEPTION for clip %d: %s\n%s", clip_idx, str(render_err)[:500], tb_render)
                add_system_log(video_id, "ERROR", "[STEP 10/10]",
                               f"❌ Render EXCEPTION klip {clip_idx}: {str(render_err)[:500]}", tb_render)

        mark_status(video_id, "COMPLETED")
        msg_done = f"🎉 Batch selesai! {rendered_count}/{total_extracted} klip viral berhasil dirender (Multimodal 2026)!"
        logger.info(msg_done)
        add_system_log(video_id, "INFO", "COMPLETED", msg_done)
        return True

    except Exception as e:
        tb_str = tb_module.format_exc()
        err_msg = f"Kegagalan kritis pemrosesan video '{video_id}': {str(e)}"
        logger.error("%s\n%s", err_msg, tb_str)
        add_system_log(video_id, "ERROR", "FAILED", err_msg, tb_str)
        mark_status(video_id, "FAILED", error_message=f"{err_msg}\n\nTraceback:\n{tb_str}")
        return False

    finally:
        cleanup_temp_workspace()



def main_loop() -> None:
    """Main infinite operational loop for 24/7 autonomous deployment."""
    logger.info("Initializing 24/7 AI Clipper Engine...")
    init_db()

    groq_client = ResilientGroqClient()
    logger.info("Bot engine operational! Entering 24/7 infinite clipping loop...")

    last_mode = None

    while True:
        try:
            # Dynamically read active mode setting from SQLite ('PODCAST' or 'WINDAH')
            active_mode = get_setting("active_mode", "PODCAST").upper().strip()
            
            if active_mode != last_mode:
                logger.info("⚡ MODE SWITCH DETECTED: Active Mode is now '%s'", active_mode)
                last_mode = active_mode

            if active_mode == "WINDAH":
                force_gaming = True
                logger.info("🎮 [WINDAH GAMING MODE ACTIVE] Mode 1 Auto-feed STOPPED. Checking for manual YouTube URL inputs...")
                videos = get_unprocessed_custom_candidates()
            else:
                feed_url = SOURCE_FEED_URL
                force_gaming = False
                logger.info("🎙️ [PODCAST MODE ACTIVE] Fetching latest feeds from configured Podcast channels...")
                videos = YouTubeFetcher.get_latest_videos(feed_url)


            processed_any = False
            failed_attempts = 0
            for item in videos:
                # Re-verify active mode before processing each video candidate
                current_mode = get_setting("active_mode", "PODCAST").upper().strip()
                if current_mode != active_mode:
                    logger.warning("Active mode switched from %s to %s mid-cycle. Aborting current feed queue...", active_mode, current_mode)
                    break

                v_id = item["id"]
                if is_processed(v_id):
                    logger.info("Video ID '%s' already processed. Skipping...", v_id)
                    continue

                logger.info("Found unprocessed candidate video ID: %s ('%s')", v_id, item.get("title"))
                success = process_single_video(item, groq_client, force_gaming_mode=force_gaming)

                if success:
                    processed_any = True
                    logger.info("Cycle success. Next video...")
                    if os.getenv("SINGLE_RUN", "false").lower() in ("true", "1", "yes"):
                        logger.info("SINGLE_RUN mode active. Exiting process after successful run.")
                        return
                    time.sleep(5)  # Brief pause before checking next video
                else:
                    failed_attempts += 1
                    logger.warning("Video processing failed for candidate '%s' (Attempt %d/3).", v_id, failed_attempts)
                    if failed_attempts >= 3:
                        logger.warning("Reached maximum candidate retry limit (3 attempts). Exiting cycle cleanly.")
                        if os.getenv("SINGLE_RUN", "false").lower() in ("true", "1", "yes"):
                            return
                        break
                    continue

            if not processed_any:
                logger.info("No new unprocessed videos found in %s feed. Sleeping with 2s mode polling...", active_mode)
                if os.getenv("SINGLE_RUN", "false").lower() in ("true", "1", "yes"):
                    logger.info("SINGLE_RUN mode active. Exiting cleanly.")
                    return

                # Sleep in 2-second increments so mode toggle takes effect immediately
                for _ in range(60):  # Total ~120s sleep, polling every 2s
                    time.sleep(2)
                    check_mode = get_setting("active_mode", "PODCAST").upper().strip()
                    if check_mode != active_mode:
                        logger.info("⚡ Mode switched to '%s' during idle sleep! Waking up immediately...", check_mode)
                        break

        except KeyboardInterrupt:
            logger.info("Received termination signal (KeyboardInterrupt). Shutting down bot gracefully.")
            sys.exit(0)
        except Exception as e:
            logger.critical("Uncaught error in main loop: %s. Sleeping %ds before continuing...", str(e), RETRY_DELAY_SEC, exc_info=True)
            time.sleep(RETRY_DELAY_SEC)



if __name__ == "__main__":
    main_loop()
