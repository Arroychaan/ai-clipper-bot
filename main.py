"""
24/7 Automated Video Clipping and Publishing Engine for ai-clipper-bot.
Runs an infinite fault-tolerant loop on Linux, executing feed fetching, AI transcription,
Llama clip selection, audio silence calibration, vertical FFmpeg rendering, and multi-platform publishing.
"""

import os
import sys
import time
import glob
import logging
from typing import List, Dict, Any

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
    PODCAST_FEEDS
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


def process_single_video(
    video_item: Dict[str, str],
    groq_client: ResilientGroqClient,
    force_gaming_mode: bool = False
) -> bool:
    """
    Executes the clipping pipeline for a single YouTube video.
    Guarantees atomic file cleanup using try...finally.
    """
    video_id = video_item.get("id") or video_item.get("video_id") or ""
    video_url = video_item["url"]
    video_title = video_item.get("title", "YouTube Video")

    
    logger.info("==================================================")
    import traceback
    from core.db_manager import add_system_log

    logger.info("Processing Candidate Video: %s (%s)", video_title, video_url)
    logger.info("==================================================")

    # 1. Update DB state to PROCESSING
    msg_start = f"Inisialisasi pemrosesan klip instan untuk video '{video_title}' ({video_id})"
    logger.info("👉 [STEP 1/6] %s", msg_start)
    add_system_log(video_id, "INFO", "[STEP 1/6]", msg_start)
    mark_status(video_id, "PROCESSING")

    audio_path = None
    video_path = None
    sub_path = None
    output_clip_path = None

    try:
        # 2. Get video transcript
        msg_trans = f"Mengambil transkrip/subtitel YouTube..."
        logger.info("👉 [STEP 2/6] %s", msg_trans)
        transcript_data = YouTubeFetcher.fetch_transcript(video_id)

        
        audio_path = None
        if not transcript_data:
            msg_whisper = "Transkrip langsung tidak tersedia. Mengunduh audio & menggunakan Groq Whisper Large v3..."
            logger.info("👉 %s", msg_whisper)
            add_system_log(video_id, "INFO", "[STEP 2/6]", msg_whisper)
            try:
                _, audio_path = YouTubeFetcher.download_audio(video_url)
                transcript_data = groq_client.transcribe_audio(audio_path)
            except Exception as audio_err:
                tb_audio = traceback.format_exc()
                err_msg = f"Gagal mengunduh/transkrip audio: {str(audio_err)}"
                logger.warning(err_msg)
                add_system_log(video_id, "ERROR", "[STEP 2/6]", err_msg, tb_audio)
                mark_status(video_id, "FAILED", error_message=f"{err_msg}\n\nTraceback:\n{tb_audio}")
                return         # 3. Extract multiple viral clips (5 to 20 clips) via Groq Llama 3.3 70B
        msg_ai = "Mengevaluasi & mengekstrak 5-20 momen klip viral terbaik (Skor >= 95) via Groq Llama 3.3 70B..."
        logger.info("👉 [STEP 3/6] %s", msg_ai)
        add_system_log(video_id, "INFO", "[STEP 3/6]", msg_ai)
        
        viral_clips = groq_client.extract_multiple_viral_clips(transcript_data)
        
        if not viral_clips:
            warn_msg = f"Tidak ditemukan kandidat klip dengan skor viral >= {MIN_VIRAL_SCORE}. Melewati render."
            logger.warning(warn_msg)
            add_system_log(video_id, "WARNING", "[STEP 3/6]", warn_msg)
            mark_status(video_id, "COMPLETED")
            return True

        total_extracted = len(viral_clips)
        msg_summary = f"🎉 Terdeteksi {total_extracted} klip viral kelas atas (Skor >= 95)! Memulai batch rendering..."
        logger.info(msg_summary)
        add_system_log(video_id, "INFO", "[STEP 3/6]", msg_summary)

        # Batch loop through each extracted viral clip candidate
        rendered_count = 0
        for clip_idx, clip_meta in enumerate(viral_clips, start=1):
            raw_start = clip_meta["start_time"]
            raw_end = clip_meta["end_time"]
            v_score = clip_meta.get("viral_score", 95)
            title = clip_meta.get("title", f"Viral Clip {clip_idx}")
            caption = clip_meta.get("caption", title)
            hashtags_str = clip_meta.get("hashtags_str", "#fyp #viral #shorts #trending")

            # 4. Calibrate cut timestamps
            msg_calib = f"[{clip_idx}/{total_extracted}] Mengalibrasi waktu potong klip '{title}' ({raw_start}s - {raw_end}s)..."
            logger.info("👉 [STEP 4/6] %s", msg_calib)
            add_system_log(video_id, "INFO", "[STEP 4/6]", msg_calib)
            if audio_path and os.path.exists(audio_path):
                start_sec, end_sec = calibrate_cut_timestamps(audio_path, raw_start, raw_end)
            else:
                start_sec, end_sec = max(0.0, float(raw_start)), float(raw_end)
            duration = end_sec - start_sec

            # 5. Download video stream slice
            msg_dl = f"[{clip_idx}/{total_extracted}] Mengunduh aliran video Full HD ({start_sec:.1f}s - {end_sec:.1f}s)..."
            logger.info("👉 [STEP 5/6] %s", msg_dl)
            add_system_log(video_id, "INFO", "[STEP 5/6]", msg_dl)
            video_path = YouTubeFetcher.download_video_stream(video_url, start_sec, end_sec)

            # 6. Render Full HD 9:16 vertical short
            clip_filename = f"clip_{video_id}_{int(start_sec)}.mp4"
            output_clip_path = str(CLIPS_DIR / clip_filename)
            
            import cv2
            cap = cv2.VideoCapture(video_path)
            v_fps = max(1.0, cap.get(cv2.CAP_PROP_FPS))
            v_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            v_duration = v_frames / v_fps
            cap.release()

            render_start_time = 0.0 if v_duration <= (duration + 15.0) else start_sec

            sub_ass_path = str(TEMP_DIR / f"{video_id}_sub_{clip_idx}.ass")
            from core.audio_processor import generate_word_level_ass
            try:
                generate_word_level_ass(
                    words=transcript_data.get("words", []),
                    start_sec=start_sec,
                    end_sec=end_sec,
                    output_ass_path=sub_ass_path
                )
            except Exception as sub_err:
                logger.warning("Failed to generate ASS subtitles: %s", str(sub_err))
                sub_ass_path = None

            if force_gaming_mode:
                msg_render = f"🎮 [{clip_idx}/{total_extracted}] [MODE WINDAH GAMING] Merender Split-Screen Full HD (Skor {v_score}) -> {clip_filename}..."
                logger.info("👉 [STEP 6/6] %s", msg_render)
                add_system_log(video_id, "INFO", "[STEP 6/6]", msg_render)
                facecam_coords = detect_streamer_facecam(video_path)
                render_success = render_gaming_split_shorts(
                    input_video=video_path,
                    start_time=render_start_time,
                    duration=duration,
                    output_path=output_clip_path,
                    facecam_coords=facecam_coords,
                    subtitle_path=sub_ass_path
                )
            else:
                msg_render = f"🎙️ [{clip_idx}/{total_extracted}] [MODE PODCAST] Merender Split-Screen Full HD (Skor {v_score}) -> {clip_filename}..."
                logger.info("👉 [STEP 6/6] %s", msg_render)
                add_system_log(video_id, "INFO", "[STEP 6/6]", msg_render)
                render_success = render_vertical_shorts(
                    input_video=video_path,
                    start_time=render_start_time,
                    duration=duration,
                    output_path=output_clip_path,
                    subtitle_path=sub_ass_path
                )

            if render_success and os.path.exists(output_clip_path) and os.path.getsize(output_clip_path) >= 100000:
                clip_id = f"{video_id}_{int(start_sec)}"
                save_clip(
                    clip_id=clip_id,
                    video_id=video_id,
                    title=title,
                    start_time=start_sec,
                    end_time=end_sec,
                    clip_path=clip_filename,
                    status="READY",
                    viral_score=v_score,
                    caption=caption,
                    hashtags=hashtags_str
                )
                rendered_count += 1
                add_system_log(video_id, "INFO", "[STEP 6/6]", f"🎉 Klip [{clip_idx}/{total_extracted}] '{title}' (Skor {v_score}) berhasil dibuat!")

        mark_status(video_id, "COMPLETED")
        msg_done = f"🎉 Batch pemrosesan selesai! {rendered_count} klip viral (Skor >= 95) berhasil dirender & disimpan ke Dashboard!"
        logger.info(msg_done)
        add_system_log(video_id, "INFO", "COMPLETED", msg_done)
        return True


    except Exception as e:
        tb_str = traceback.format_exc()
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
                feed_url = ",".join(PODCAST_FEEDS)
                force_gaming = False
                logger.info("🎙️ [PODCAST MODE ACTIVE] Fetching latest feeds from 9 Podcast channels...")
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
