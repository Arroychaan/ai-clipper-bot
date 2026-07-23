"""
Automated YouTube Shorts uploader using YouTube Data API v3 and Google OAuth2.
Handles resumable video uploads, metadata population, and token caching.
"""

import os
import logging
from typing import List, Optional, Any

try:
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build, Resource  # type: ignore
    from googleapiclient.http import MediaFileUpload  # type: ignore
except ImportError:
    Request = None  # type: ignore
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    build = None  # type: ignore
    Resource = None  # type: ignore
    MediaFileUpload = None  # type: ignore

from config import YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES: List[str] = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeUploader:
    """Handles OAuth2 authentication and video uploads to YouTube Shorts."""

    def __init__(self):
        self.youtube_service: Optional[Any] = self._get_authenticated_service()

    def _get_authenticated_service(self) -> Optional[Any]:
        """Loads cached credentials or authenticates via client secrets."""
        if build is None or Credentials is None:
            logger.warning("Google API client packages are not installed. Skipping YouTube integration.")
            return None

        creds: Optional[Any] = None

        if os.path.exists(YOUTUBE_TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_FILE), SCOPES)
            except Exception as e:
                logger.warning("Could not parse existing YouTube token file: %s", str(e))

        # Refresh or prompt authorization if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("Refreshing expired YouTube OAuth2 access token...")
                    creds.refresh(Request())
                except Exception as e:
                    logger.error("Failed to refresh YouTube token: %s", str(e))
                    creds = None

            if not creds:
                if not os.path.exists(YOUTUBE_CLIENT_SECRETS_FILE):
                    logger.warning(
                        "YouTube client secrets file not found at '%s'. YouTube uploading will be skipped.",
                        YOUTUBE_CLIENT_SECRETS_FILE
                    )
                    return None

                logger.info("Initiating local server OAuth2 authorization flow...")
                flow = InstalledAppFlow.from_client_secrets_file(str(YOUTUBE_CLIENT_SECRETS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for future executions
            with open(YOUTUBE_TOKEN_FILE, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
            logger.info("Saved fresh YouTube OAuth2 token to: %s", YOUTUBE_TOKEN_FILE)

        return build("youtube", "v3", credentials=creds)

    def upload_short(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str]
    ) -> Optional[str]:
        """
        Uploads a vertical short video to YouTube.
        
        Args:
            video_path: Path to rendered MP4 video file.
            title: Title for the Short (should include #Shorts).
            description: Detailed description text.
            tags: List of tag strings.
            
        Returns:
            Optional[str]: YouTube video ID on success, None if skipped or failed.
        """
        if not self.youtube_service:
            logger.warning("YouTube service is not authenticated. Skipping YouTube upload.")
            return None

        if not os.path.exists(video_path):
            logger.error("Cannot upload missing file to YouTube: %s", video_path)
            return None

        # Format title to include #Shorts if not present
        if "#Shorts" not in title and "#shorts" not in title:
            title = f"{title} #Shorts"

        body = {
            "snippet": {
                "title": title[:100],  # Max 100 characters for YouTube title
                "description": description,
                "tags": tags,
                "categoryId": "24"     # Category: Entertainment
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        logger.info("Uploading video to YouTube Shorts: '%s'...", title)
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

        try:
            request = self.youtube_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info("YouTube Upload Progress: %d%%", int(status.progress() * 100))

            video_id = response.get("id")
            logger.info("Successfully published YouTube Short! Video URL: https://youtube.com/shorts/%s", video_id)
            return video_id
        except Exception as e:
            logger.error("YouTube upload failed: %s", str(e))
            return None
