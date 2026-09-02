import os
import time
import json
import logging
import httplib2
from typing import List, Optional, Dict, Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class YouTubeUploader:
    def __init__(self, token_file: str, client_secret_file: Optional[str] = None):
        self.token_file = token_file
        self.client_secret_file = client_secret_file
        self.credentials = self._get_credentials()
        self.youtube = build("youtube", "v3", credentials=self.credentials)

    def _get_credentials(self) -> Credentials:
        if not os.path.exists(self.token_file):
            raise FileNotFoundError(
                f"OAuth token file not found: {self.token_file}. "
                f"Please run 'python reauth_nobrowser.py <channel_id>' to generate it."
            )

        with open(self.token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        credentials = Credentials.from_authorized_user_info(token_data, SCOPES)
        if credentials.expired and credentials.refresh_token:
            logger.info("OAuth token expired, refreshing with Google...")
            credentials.refresh(Request())
            # Save the refreshed token
            with open(self.token_file, "w", encoding="utf-8") as f:
                f.write(credentials.to_json())
            logger.info("Refreshed token saved successfully.")

        return credentials

    def upload_short(
        self,
        video_path: str,
        title: str,
        description: str = "",
        category_id: str = "20",
        tags: Optional[List[str]] = None,
        privacy_status: str = "public"
    ) -> Optional[str]:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file to upload not found: {video_path}")

        if tags is None:
            tags = []

        # Ensure #Shorts tag is present for YouTube algorithm indexing
        if "Shorts" not in tags and "shorts" not in tags:
            tags.append("Shorts")

        # Clean title & ensure length limit of 100 characters
        clean_title = title.strip()
        if not clean_title:
            clean_title = "Gaming Highlights #Shorts"
        if len(clean_title) > 90:
            clean_title = clean_title[:87] + "..."
        if "#shorts" not in clean_title.lower():
            clean_title = f"{clean_title} #Shorts"
        if len(clean_title) > 100:
            clean_title = clean_title[:100]

        body = {
            "snippet": {
                "title": clean_title,
                "description": description.strip(),
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            }
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            chunksize=1024 * 1024 * 4, # 4MB chunks
            resumable=True
        )

        logger.info(f"Initiating YouTube Shorts upload: '{clean_title}' (Category: {category_id})...")
        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        retries = 5
        retry_delay = 5

        for attempt in range(retries):
            try:
                status, response = request.next_chunk()
                while response is None:
                    if status:
                        pct = int(status.progress() * 100)
                        logger.info(f"Upload progress: {pct}%")
                    status, response = request.next_chunk()

                if response and "id" in response:
                    video_id = response["id"]
                    logger.info(f"Successfully uploaded YouTube Short! Video ID: {video_id}")
                    return video_id
            except HttpError as ex:
                if ex.resp.status == 403 and "authenticatedUserAccountSuspended" in str(ex):
                    logger.critical(f"FATAL: YouTube Channel has been suspended (403).")
                    raise
                logger.warning(f"Upload attempt {attempt + 1}/{retries} HTTP error: {ex}")
                time.sleep(retry_delay * (attempt + 1))
            except Exception as ex:
                logger.warning(f"Upload attempt {attempt + 1}/{retries} network error: {ex}")
                time.sleep(retry_delay * (attempt + 1))

        logger.error(f"Failed to upload video {video_path} after {retries} attempts.")
        return None
