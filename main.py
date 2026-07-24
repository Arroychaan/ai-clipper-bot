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
    video_id = video_item["id"]
    video_url = video_item["url"]
    video_title = video_item.get("title", "YouTube Video")
    
    logger.info("==================================================")
    logger.info("Processing Candidate Video: %s (%s)", video_title, video_url)
    logger.info("==================================================")

    # 1. Update DB state to PROCESSING
    logger.info("👉 [STEP 1/7] Updating DB status to PROCESSING...")
    mark_status(video_id, "PROCESSING")

    audio_path = None
    video_path = None
    sub_path = None
    output_clip_path = None

    try:
        # 2. Get video transcript
        logger.info("👉 [STEP 2/7] Fetching video transcript...")
        transcript_data = YouTubeFetcher.get_transcript_direct(video_id)
        
        audio_path = None
        if not transcript_data:
            logger.info("Direct transcript unavailable. Downloading audio for Groq Whisper...")
            try:
                _, audio_path = YouTubeFetcher.download_audio(video_url)
                logger.info("👉 [STEP 3/7] Transcribing audio via Groq Whisper Large v3...")
                transcript_data = groq_client.transcribe_audio(audio_path)
            except Exception as audio_err:
                logger.warning("Audio download/transcription failed for candidate '%s': %s. Marking FAILED and skipping...", video_id, str(audio_err))
                mark_status(video_id, "FAILED", error_message=str(audio_err))
                return False

        else:
            logger.info("👉 [STEP 3/7] Direct transcript retrieved instantly!")

        # 4. Extract viral clip segment via Groq Llama 3.3 70B
        logger.info("👉 [STEP 4/7] Evaluating viral hook score via Groq Llama 3.3 70B...")
        clip_meta = groq_client.extract_viral_clip(transcript_data)
        
        viral_score = clip_meta.get("viral_score", 90)
        logger.info("Evaluated Viral Hook Score: %d/100 (Threshold: %d)", viral_score, MIN_VIRAL_SCORE)

        if viral_score < MIN_VIRAL_SCORE:
            logger.warning(
                "⚠️ Clip candidate for video '%s' scored %d/100, which is below the minimum threshold of %d. Skipping render.",
                video_id, viral_score, MIN_VIRAL_SCORE
            )
            mark_status(video_id, "COMPLETED")
            return True

        raw_start = clip_meta["start_time"]
        raw_end = clip_meta["end_time"]
        title = clip_meta.get("title", "Viral Clip")
        caption = clip_meta.get("caption", title)
        hashtags_str = clip_meta.get("hashtags_str", "#fyp #viral #shorts #trending")

        # 5. Calibrate cut timestamps via silence detection
        logger.info("👉 [STEP 5/7] Calibrating cut timestamps...")
        if audio_path and os.path.exists(audio_path):
            start_sec, end_sec = calibrate_cut_timestamps(audio_path, raw_start, raw_end)
        else:
            start_sec, end_sec = max(0.0, float(raw_start)), float(raw_end)
        duration = end_sec - start_sec

        # Download fast video stream slice
        logger.info("👉 [STEP 6/7] Downloading MP4 video stream section...")
        video_path = YouTubeFetcher.download_video_stream(video_url, start_sec, end_sec)

        # Extract audio slice from downloaded video_path for Groq Whisper v3 precision word timestamps
        logger.info("👉 [STEP 5.5/7] Extracting clip audio slice for Groq Whisper v3 0-delay word timestamps...")
        clip_audio_path = os.path.join(TEMP_DIR, f"{video_id}_clip_audio.wav")
        clip_words = []
        try:
            cmd_cut_audio = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                clip_audio_path
            ]
            subprocess.run(cmd_cut_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            
            logger.info("Running Groq Whisper Large v3 on clip audio slice (%s)...", clip_audio_path)
            clip_transcription = groq_client.transcribe_audio(clip_audio_path)
            clip_words = clip_transcription.get("words", [])
            logger.info("Groq Whisper Large v3 extracted %d precise waveform words for clip!", len(clip_words))
        except Exception as whisper_err:
            logger.warning("Clip audio Whisper transcription failed (%s). Falling back to segment interpolation...", str(whisper_err))

        # Generate CapCut/TikTok Master Auto-FYP ASS subtitles with 0-delay waveform timestamps
        ass_filename = f"{video_id}_subtitles.ass"
        sub_path = os.path.join(TEMP_DIR, ass_filename)
        
        # If clip_words came from clip_audio_path (which starts at 0.0s), timestamps are relative to 0.0s!
        use_relative_zero = len(clip_words) > 0
        generate_ass_subtitle_file(
            words=clip_words if use_relative_zero else (transcript_data.get("words") or transcript_data.get("segments", [])),
            start_sec=0.0 if use_relative_zero else start_sec,
            end_sec=duration if use_relative_zero else end_sec,
            output_ass_path=sub_path,
            clip_audio_path=clip_audio_path if os.path.exists(clip_audio_path) else None
        )



        # 6. Render Full HD 9:16 vertical short using FFmpeg
        clip_filename = f"clip_{video_id}_{int(start_sec)}.mp4"
        output_clip_path = str(CLIPS_DIR / clip_filename)
        
        if force_gaming_mode:
            logger.info("🎮 [WINDAH GAMING MODE ACTIVE] Running AI OpenCV Facecam Tracker -> %s...", output_clip_path)
            facecam_coords = detect_streamer_facecam(video_path)
            render_success = render_gaming_split_shorts(
                input_video=video_path,
                start_time=start_sec,
                duration=duration,
                output_path=output_clip_path,
                facecam_coords=facecam_coords,
                subtitle_path=sub_path
            )
        else:
            logger.info("🎙️ [PODCAST MODE ACTIVE] Rendering Full HD 1080x1920 (9:16) 60fps vertical short -> %s...", output_clip_path)
            render_success = render_vertical_shorts(
                input_video=video_path,
                start_time=start_sec,
                duration=duration,
                output_path=output_clip_path,
                subtitle_path=sub_path
            )

        if not render_success or not os.path.exists(output_clip_path) or os.path.getsize(output_clip_path) < 100000:
            raise RuntimeError(f"FFmpeg vertical render failed or output clip is corrupted (< 100KB) for video {video_id}")



        # Save clip metadata into SQLite database
        clip_id = f"{video_id}_{int(start_sec)}"
        save_clip(
            clip_id=clip_id,
            video_id=video_id,
            video_title=video_title,
            clip_title=title,
            caption=caption,
            hashtags=hashtags_str,
            viral_score=viral_score,
            duration=round(duration, 1),
            clip_path=clip_filename
        )

        # Mark DB status to COMPLETED
        mark_status(video_id, "COMPLETED")
        logger.info("🎉 Clip successfully generated & saved to PWA Dashboard! Clip ID: %s (Viral Score: %d)", clip_id, viral_score)
        return True

    except Exception as e:
        logger.error("Error processing video ID '%s': %s", video_id, str(e), exc_info=True)
        mark_status(video_id, "FAILED", error_message=str(e))
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
