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
    RAMPUP_MODE,
    RAMPUP_INTERVAL_SEC,
    STANDARD_INTERVAL_SEC,
    RETRY_DELAY_SEC,
    SOURCE_FEED_URL
)
from core.db_manager import init_db, is_processed, mark_status
from core.groq_manager import ResilientGroqClient
from core.fetcher import YouTubeFetcher
from core.audio_processor import calibrate_cut_timestamps, generate_subtitle_file
from core.ffmpeg_renderer import render_vertical_shorts
from uploader.youtube_uploader import YouTubeUploader
from uploader.tiktok_uploader import TikTokUploader

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
    ATOMIC CLEANUP: Explicitly purges all temporary files (.mp4, .wav, .srt)
    from TEMP_DIR to guarantee zero disk growth and zero memory leaks.
    """
    logger.info("Executing atomic workspace cleanup in: %s", TEMP_DIR)
    patterns = ["*.mp4", "*.wav", "*.srt", "*.webm", "*.mkv"]
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
    yt_uploader: YouTubeUploader,
    tt_uploader: TikTokUploader
) -> bool:
    """
    Executes the full pipeline for a single YouTube video.
    Guarantees atomic file cleanup using try...finally.
    
    Returns:
        bool: True if video was successfully processed and published.
    """
    video_id = video_item["id"]
    video_url = video_item["url"]
    
    logger.info("==================================================")
    logger.info("Starting processing pipeline for video ID: %s", video_id)
    logger.info("==================================================")

    # 1. Update DB state to PROCESSING
    logger.info("👉 [STEP 1/9] Updating DB status to PROCESSING...")
    mark_status(video_id, "PROCESSING")

    audio_path = None
    video_path = None
    srt_path = None
    output_clip_path = None

    try:
        # 2. Download audio stream (16kHz WAV, lightweight 30MB)
        logger.info("👉 [STEP 2/9] Downloading audio stream from YouTube...")
        _, audio_path = YouTubeFetcher.download_audio(video_url)

        # 3. Transcribe audio via Groq Whisper v3
        logger.info("👉 [STEP 3/9] Transcribing audio via Groq Whisper Large v3...")
        transcript_data = groq_client.transcribe_audio(audio_path)

        # 4. Extract viral clip segment via Groq Llama 3.3 70B
        logger.info("👉 [STEP 4/9] Extracting viral clip segment via Groq Llama 3.3 70B...")
        clip_meta = groq_client.extract_viral_clip(transcript_data)
        raw_start = clip_meta["start_time"]
        raw_end = clip_meta["end_time"]
        title = clip_meta.get("title", "Viral Clip")
        hashtags = clip_meta.get("hashtags", ["#Shorts", "#Viral"])

        # 5. Calibrate cut timestamps via silence detection
        logger.info("👉 [STEP 5/9] Calibrating cut timestamps via silence detection...")
        start_sec, end_sec = calibrate_cut_timestamps(audio_path, raw_start, raw_end)
        duration = end_sec - start_sec

        # 6. Download fast 1080p MP4 video clip slice (35s slice ONLY - 50x faster!)
        logger.info("👉 [STEP 6/9] Downloading fast 1080p MP4 video clip slice (35s section)...")
        video_path = YouTubeFetcher.download_video_stream(video_url, start_sec, end_sec)

        # 7. Generate interactive SRT subtitles
        logger.info("👉 [STEP 7/9] Generating interactive SRT subtitles...")
        srt_filename = f"{video_id}_subtitles.srt"
        srt_path = os.path.join(TEMP_DIR, srt_filename)
        generate_subtitle_file(
            words=transcript_data.get("words", []),
            start_sec=start_sec,
            end_sec=end_sec,
            output_srt_path=srt_path
        )

        # 8. Render 9:16 vertical short using 1-pass CPU FFmpeg filtergraph
        logger.info("👉 [STEP 8/9] Rendering 9:16 vertical short using 1-pass FFmpeg...")
        output_clip_name = f"{video_id}_short.mp4"
        output_clip_path = os.path.join(TEMP_DIR, output_clip_name)
        
        render_success = render_vertical_shorts(
            input_video=video_path,
            start_time=start_sec,
            duration=duration,
            output_path=output_clip_path,
            subtitle_path=srt_path
        )

        if not render_success or not os.path.exists(output_clip_path):
            raise RuntimeError(f"FFmpeg vertical render failed for video {video_id}")

        # 9. Multi-Platform Automated Publishing
        logger.info("👉 [STEP 9/9] Publishing video to YouTube Shorts & TikTok...")
        description = f"{title}\n\n" + " ".join(hashtags)
        
        yt_uploader.upload_short(
            video_path=output_clip_path,
            title=title,
            description=description,
            tags=[h.replace("#", "") for h in hashtags]
        )

        tt_uploader.upload_short(
            video_path=output_clip_path,
            caption=title,
            hashtags=hashtags
        )

        # 10. Mark DB status to COMPLETED
        mark_status(video_id, "COMPLETED")
        logger.info("Successfully completed pipeline for video ID: %s", video_id)
        return True

    except Exception as e:
        logger.error("Error processing video ID '%s': %s", video_id, str(e), exc_info=True)
        mark_status(video_id, "FAILED", error_message=str(e))
        return False

    finally:
        # ATOMIC CLEANUP: Always remove temporary files from TEMP_DIR
        cleanup_temp_workspace()


def main_loop() -> None:
    """Main infinite operational loop for 24/7 autonomous deployment."""
    logger.info("Initializing ai-clipper-bot engine...")
    init_db()

    groq_client = ResilientGroqClient()
    yt_uploader = YouTubeUploader()
    tt_uploader = TikTokUploader()

    # Determine posting interval based on Ramp-Up setting
    if RAMPUP_MODE:
        sleep_interval = RAMPUP_INTERVAL_SEC
        logger.info("MODE: Account Ramp-Up active (3 clips/day cadence, sleep interval = %ds)", sleep_interval)
    else:
        sleep_interval = STANDARD_INTERVAL_SEC
        logger.info("MODE: Standard Production active (10 clips/day cadence, sleep interval = %ds)", sleep_interval)

    logger.info("Bot engine operational! Entering 24/7 infinite loop...")

    while True:
        try:
            logger.info("Checking video feed from: %s", SOURCE_FEED_URL)
            videos = YouTubeFetcher.get_latest_videos(SOURCE_FEED_URL)

            processed_any = False
            for item in videos:
                v_id = item["id"]
                if is_processed(v_id):
                    logger.info("Video ID '%s' already processed. Skipping...", v_id)
                    continue

                logger.info("Found unprocessed candidate video ID: %s ('%s')", v_id, item.get("title"))
                success = process_single_video(item, groq_client, yt_uploader, tt_uploader)
                
                if success:
                    processed_any = True
                    logger.info("Cycle success.")
                    if os.getenv("SINGLE_RUN", "false").lower() in ("true", "1", "yes"):
                        logger.info("SINGLE_RUN mode active. Exiting process after successful run.")
                        return
                    logger.info("Sleeping for %d seconds before next upload...", sleep_interval)
                    time.sleep(sleep_interval)
                    break  # Process 1 video per cycle interval
                else:
                    logger.warning("Video processing failed for candidate '%s'. Trying next candidate in feed...", v_id)
                    continue

            if not processed_any:
                logger.info("No new unprocessed videos found in feed.")
                if os.getenv("SINGLE_RUN", "false").lower() in ("true", "1", "yes"):
                    logger.info("SINGLE_RUN mode active. Exiting cleanly.")
                    return
                logger.info("Sleeping for %d seconds...", RETRY_DELAY_SEC * 5)
                time.sleep(RETRY_DELAY_SEC * 5)

        except KeyboardInterrupt:
            logger.info("Received termination signal (KeyboardInterrupt). Shutting down bot gracefully.")
            sys.exit(0)
        except Exception as e:
            logger.critical("Uncaught error in main loop: %s. Sleeping %ds before continuing...", str(e), RETRY_DELAY_SEC, exc_info=True)
            time.sleep(RETRY_DELAY_SEC)


if __name__ == "__main__":
    main_loop()
