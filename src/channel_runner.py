import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from .config import ChannelConfig
from .db import Database
from .tiktok_downloader import TikTokDownloader
from .video_editor import VideoEditor
from .youtube_uploader import YouTubeUploader
from .notifier import DiscordNotifier

logger = logging.getLogger(__name__)

class ChannelRunner:
    def __init__(
        self,
        config: ChannelConfig,
        db: Database,
        downloader: Optional[TikTokDownloader] = None,
        editor: Optional[VideoEditor] = None,
        uploader: Optional[YouTubeUploader] = None,
        notifier: Optional[DiscordNotifier] = None
    ):
        self.config = config
        self.db = db
        self.downloader = downloader or TikTokDownloader()
        self.editor = editor or VideoEditor()
        self.notifier = notifier or DiscordNotifier()
        self.uploader = uploader # Will be initialized on demand if not dry-run

    def _get_uploader(self) -> YouTubeUploader:
        if self.uploader is None:
            self.uploader = YouTubeUploader(
                token_file=self.config.oauth_token_file,
                client_secret_file=self.config.google_credentials_file
            )
        return self.uploader

    def run_slot(self, slot: int, dry_run: bool = False) -> bool:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        channel_id = self.config.id
        logger.info(f"=== Starting Run for Channel '{channel_id}' | Slot #{slot} | Date: {today_str} (DryRun={dry_run}) ===")

        # 1. Per-day Guard Check
        if not dry_run and self.db.is_slot_already_ran_today(channel_id, slot, today_str):
            logger.info(f"Slot #{slot} has already succeeded today for channel '{channel_id}'. Skipping as per-day guard.")
            self.db.record_run(channel_id, slot, "skipped", message="Per-day guard: Already completed today.")
            return True

        # 2. Check Pending Retries First
        posted_ids = self.db.get_posted_ids(channel_id)
        pending_rows = self.db.get_pending_retries(channel_id, today_str)
        candidates: List[Dict[str, Any]] = []

        if pending_rows:
            logger.info(f"Found {len(pending_rows)} pending retry candidate(s) for {channel_id}.")
            for row in pending_rows:
                candidates.append({
                    "id": row["tiktok_id"],
                    "url": f"https://www.tiktok.com/@{self.config.tiktok_username}/video/{row['tiktok_id']}",
                    "title": row["title"] or f"Highlight #{row['tiktok_id']}",
                    "view_count": 0,
                    "is_retry": True,
                    "retry_count": row["retry_count"]
                })

        # 3. Fetch TikTok Profile if needed
        primary_username = self.config.tiktok_username
        if slot == 2 and self.config.tiktok_username_slot2:
            primary_username = self.config.tiktok_username_slot2

        unposted_videos: List[Dict[str, Any]] = []
        raw_videos = self.downloader.list_user_videos(primary_username, limit=150)
        
        # Fallback to primary if slot2 secondary account ran dry
        if not raw_videos and slot == 2 and self.config.tiktok_username_slot2:
            logger.warning(f"Secondary account @{self.config.tiktok_username_slot2} empty. Falling back to primary @{self.config.tiktok_username}.")
            primary_username = self.config.tiktok_username
            raw_videos = self.downloader.list_user_videos(primary_username, limit=150)

        for v in raw_videos:
            if v["id"] not in posted_ids:
                # Check optional duration limit
                if v.get("duration", 0) <= self.config.shorts_max_seconds:
                    unposted_videos.append(v)

        logger.info(f"Unposted videos available for @{primary_username}: {len(unposted_videos)}")

        # 4. Mode Selection (Slot Picking Logic)
        if self.config.upload_mode == "popular_split":
            if slot == 1:
                # Slot 1: Newest unposted (default list order from profile is newest first)
                candidates.extend(unposted_videos)
            else:
                # Slot 2: Most-viewed unposted (sorted by view_count descending)
                sorted_by_views = sorted(unposted_videos, key=lambda x: x.get("view_count", 0), reverse=True)
                candidates.extend(sorted_by_views)
        elif self.config.upload_mode == "popular_only":
            sorted_by_views = sorted(unposted_videos, key=lambda x: x.get("view_count", 0), reverse=True)
            candidates.extend(sorted_by_views)
        else:
            # short_only / default: newest
            candidates.extend(unposted_videos)

        if not candidates:
            logger.warning(f"No content available to post for {channel_id} (Slot #{slot}).")
            if not dry_run:
                self.db.record_run(channel_id, slot, "no_content", message="No unposted videos found.")
            return True

        # 5. Process Candidates with Fallback
        max_tries = min(len(candidates), self.config.max_download_candidates)
        logger.info(f"Evaluating top {max_tries} candidate(s)...")

        for idx in range(max_tries):
            cand = candidates[idx]
            cand_id = cand["id"]
            cand_title = cand.get("title", "").strip() or f"Highlight #{cand_id}"
            cand_url = cand.get("url") or f"https://www.tiktok.com/@{primary_username}/video/{cand_id}"
            is_retry = cand.get("is_retry", False)
            retry_count = cand.get("retry_count", 0)

            logger.info(f"Trying candidate [{idx + 1}/{max_tries}] TikTok ID: {cand_id} ('{cand_title[:40]}...')")

            # Download
            downloaded_file = self.downloader.download_video(cand_url)
            if not downloaded_file:
                logger.warning(f"Failed download for {cand_id}. Queuing for retry.")
                if not dry_run:
                    self.db.record_posted_video(
                        tiktok_id=cand_id,
                        channel_id=channel_id,
                        status="pending_retry",
                        title=cand_title,
                        retry_count=retry_count + 1
                    )
                continue

            # Edit and optimize
            edited_file = self.editor.edit_and_optimize_short(downloaded_file)
            if not edited_file:
                logger.warning(f"Video editing / audio check failed for {cand_id}.")
                if os.path.exists(downloaded_file):
                    os.remove(downloaded_file)
                if not dry_run:
                    self.db.record_posted_video(
                        tiktok_id=cand_id,
                        channel_id=channel_id,
                        status="pending_retry",
                        title=cand_title,
                        retry_count=retry_count + 1
                    )
                continue

            # If dry run: stop before uploading
            if dry_run:
                logger.info(f"[DRY-RUN] Success! Would have uploaded TikTok {cand_id} -> YouTube Shorts.")
                self._cleanup_files([downloaded_file, edited_file])
                return True

            # Upload to YouTube
            try:
                uploader = self._get_uploader()
                desc = f"{cand_title}\n\n{self.config.description_footer}".strip()
                yt_id = uploader.upload_short(
                    video_path=edited_file,
                    title=self.config.fixed_title or cand_title,
                    description=desc,
                    category_id=self.config.youtube_category_id,
                    tags=self.config.default_tags
                )

                if yt_id:
                    self.db.record_posted_video(
                        tiktok_id=cand_id,
                        channel_id=channel_id,
                        status="uploaded",
                        youtube_id=yt_id,
                        title=cand_title
                    )
                    self.db.record_run(channel_id, slot, "success", video_id=yt_id, message="Uploaded successfully.")
                    self.notifier.notify_success(channel_id, slot, cand_title, yt_id, cand_url)
                    logger.info(f"✨ Successfully published: https://youtu.be/{yt_id}")
                    self._cleanup_files([downloaded_file, edited_file])
                    return True
                else:
                    raise RuntimeError("YouTube upload returned empty ID.")

            except Exception as ex:
                logger.error(f"Error during YouTube upload of {cand_id}: {ex}")
                self.notifier.notify_failure(channel_id, slot, str(ex), will_retry=True)
                self.db.record_posted_video(
                    tiktok_id=cand_id,
                    channel_id=channel_id,
                    status="pending_retry",
                    title=cand_title,
                    retry_count=retry_count + 1
                )
                self._cleanup_files([downloaded_file, edited_file])

        logger.error(f"Exhausted all {max_tries} candidates for channel {channel_id} (Slot #{slot}).")
        if not dry_run:
            self.db.record_run(channel_id, slot, "failed", message=f"Exhausted {max_tries} candidates without successful upload.")
        return False

    def _cleanup_files(self, filepaths: List[Optional[str]]) -> None:
        for fp in filepaths:
            if fp and os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception as ex:
                    logger.warning(f"Could not remove temporary file {fp}: {ex}")
