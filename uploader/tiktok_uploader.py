"""
Automated TikTok uploader using Playwright Python in headless mode.
Loads pre-saved session cookies to publish vertical video shorts natively via TikTok Creator Center.
"""

import os
import json
import time
import logging
from typing import Optional, List

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None  # type: ignore

from config import TIKTOK_COOKIES_FILE

logger = logging.getLogger(__name__)


class TikTokUploader:
    """Headless browser wrapper using Playwright to upload video shorts to TikTok."""

    def __init__(self):
        self.cookies_file = TIKTOK_COOKIES_FILE

    def upload_short(
        self,
        video_path: str,
        caption: str,
        hashtags: List[str]
    ) -> bool:
        """
        Uploads video clip to TikTok natively using headless Chromium with session cookies.
        
        Args:
            video_path: Path to rendered MP4 video file.
            caption: Video caption/title.
            hashtags: List of hashtags.
            
        Returns:
            bool: True if upload flow completed, False otherwise.
        """
        if sync_playwright is None:
            logger.warning("Playwright library is not installed. Skipping TikTok native upload.")
            return False

        if not os.path.exists(self.cookies_file):
            logger.warning(
                "TikTok cookies file missing at '%s'. Skipping TikTok native upload.",
                self.cookies_file
            )
            return False

        if not os.path.exists(video_path):
            logger.error("Cannot upload missing file to TikTok: %s", video_path)
            return False

        full_caption = f"{caption} " + " ".join(hashtags)

        logger.info("Initiating headless Playwright session for TikTok upload...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ]
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )

                # Inject saved session cookies
                with open(self.cookies_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)

                page = context.new_page()
                logger.info("Navigating to TikTok Studio upload page...")
                
                upload_urls = [
                    "https://www.tiktok.com/tiktokstudio/upload",
                    "https://www.tiktok.com/creator-center/upload"
                ]
                
                navigated = False
                for target_url in upload_urls:
                    try:
                        logger.info("Trying TikTok upload endpoint: %s", target_url)
                        page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
                        time.sleep(3)
                        navigated = True
                        break
                    except Exception as nav_err:
                        logger.warning("Navigation to %s failed: %s", target_url, str(nav_err))
                        continue

                if not navigated:
                    logger.error("Could not navigate to any TikTok upload URL.")
                    browser.close()
                    return False

                # Locate file input element (supports iframe fallback)
                file_input = page.query_selector('input[type="file"]')
                if not file_input:
                    frames = page.frames
                    for frame in frames:
                        file_input = frame.query_selector('input[type="file"]')
                        if file_input:
                            break

                if not file_input:
                    logger.error("Failed to find file input element on TikTok upload page. Cookies might be expired or session unauthorized.")
                    browser.close()
                    return False

                logger.info("Uploading video file to TikTok...")
                file_input.set_input_files(os.path.abspath(video_path))
                
                # Wait for video upload processing
                logger.info("Waiting for video upload processing to complete...")
                time.sleep(12)

                # Type caption text
                caption_selector = 'div[contenteditable="true"], text=Caption, [data-contents="true"]'
                try:
                    caption_elem = page.wait_for_selector(caption_selector, timeout=20000)
                    if caption_elem:
                        caption_elem.click()
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        page.keyboard.type(full_caption[:150]) # TikTok caption length limit safety
                        logger.info("Typed TikTok caption successfully!")
                except Exception as cap_err:
                    logger.warning("Could not set custom TikTok caption automatically: %s", str(cap_err))

                # Click Post button
                post_button_selector = 'button:has-text("Post"), button:has-text("Publish"), button[type="submit"]'
                try:
                    post_btn = page.wait_for_selector(post_button_selector, timeout=20000)
                    if post_btn:
                        logger.info("Clicking TikTok Post button...")
                        post_btn.click()
                        time.sleep(8)
                        logger.info("TikTok upload command completed successfully!")
                        browser.close()
                        return True
                except Exception as post_err:
                    logger.warning("Could not click TikTok Post button automatically: %s", str(post_err))

                browser.close()
                return False
        except Exception as e:
            logger.error("Playwright TikTok automation failed: %s", str(e))
            return False
