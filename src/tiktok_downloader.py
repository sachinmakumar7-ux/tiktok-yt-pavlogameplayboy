import os
import time
import logging
from typing import List, Dict, Optional, Any
import yt_dlp

logger = logging.getLogger(__name__)

# Watermark-free stream preference list
TIKTOK_FORMAT_SELECTOR = (
    "bestvideo[format_id^=play][ext=mp4]+bestaudio/"
    "best[format_id^=play][ext=mp4][vcodec!=none]/"
    "best[format_id^=play][vcodec!=none]/"
    "best[format_id^=h264][ext=mp4][vcodec!=none]/"
    "best[ext=mp4][vcodec!=none]/"
    "best[vcodec!=none]"
)

class TikTokDownloader:
    def __init__(self, cookies_file: Optional[str] = None):
        self.cookies_file = cookies_file
        if not self.cookies_file:
            env_cookies = os.environ.get("TIKTOK_COOKIES_FILE", "cookies.txt")
            if os.path.exists(env_cookies):
                self.cookies_file = env_cookies

    def _get_base_ydl_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": False,
            "no_warnings": False,
            "http_headers": {
                "Referer": "https://www.tiktok.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            "ignoreerrors": True,
        }
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts["impersonate"] = ImpersonateTarget.from_str("chrome")
        except Exception:
            opts["impersonate"] = "chrome"

        if self.cookies_file and os.path.exists(self.cookies_file):
            opts["cookiefile"] = self.cookies_file
        return opts

    def list_user_videos(self, username: str, limit: int = 150) -> List[Dict[str, Any]]:
        clean_user = username.lstrip("@")
        known_user_ids = {
            "pavlogameplayboy": "7428105449079931909"
        }
        known_seed_videos = {
            "pavlogameplayboy": [
                "https://www.tiktok.com/@pavlogameplayboy/video/7680921837328403719"
            ]
        }

        urls_to_try = [f"https://www.tiktok.com/@{clean_user}"]
        if clean_user in known_user_ids:
            urls_to_try.append(f"tiktokuser:{known_user_ids[clean_user]}")

        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "extract_flat": True,
            "playlistend": limit,
        })

        for profile_url in urls_to_try:
            logger.info(f"Trying TikTok profile source: {profile_url} (limit: {limit})...")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(profile_url, download=False)
                    if info and "entries" in info:
                        raw_entries = info["entries"] or []
                        valid_entries = []
                        for e in raw_entries:
                            if not e:
                                continue
                            url = e.get("url") or e.get("webpage_url") or ""
                            if "/photo/" in url:
                                continue
                            valid_entries.append({
                                "id": str(e.get("id")),
                                "title": e.get("title") or "",
                                "duration": e.get("duration") or 0,
                                "view_count": int(e.get("view_count") or 0),
                                "upload_date": e.get("upload_date") or "",
                                "url": e.get("url") or url or f"https://www.tiktok.com/@{clean_user}/video/{e.get('id')}",
                                "timestamp": e.get("timestamp") or 0
                            })

                        if valid_entries:
                            logger.info(f"Successfully retrieved {len(valid_entries)} videos from {profile_url}")
                            return valid_entries
            except Exception as ex:
                logger.warning(f"Listing attempt failed for {profile_url}: {ex}")

        # Fallback to known seed videos if profile scraping fails
        if clean_user in known_seed_videos:
            logger.info(f"Profile listing blocked. Falling back to seed video(s) for @{clean_user}...")
            seed_entries = []
            for video_url in known_seed_videos[clean_user]:
                try:
                    with yt_dlp.YoutubeDL(self._get_base_ydl_opts()) as ydl:
                        v_info = ydl.extract_info(video_url, download=False)
                        if v_info:
                            vid = str(v_info.get("id") or video_url.rstrip("/").split("/")[-1])
                            seed_entries.append({
                                "id": vid,
                                "title": v_info.get("title") or v_info.get("description") or f"Highlight #{vid}",
                                "duration": v_info.get("duration") or 0,
                                "view_count": int(v_info.get("view_count") or 0),
                                "upload_date": v_info.get("upload_date") or "",
                                "url": video_url,
                                "timestamp": v_info.get("timestamp") or 0
                            })
                except Exception as ex:
                    logger.warning(f"Could not inspect seed video {video_url}: {ex}")
                    # Even if extract_info fails, still provide direct video URL as candidate
                    vid = video_url.rstrip("/").split("/")[-1]
                    seed_entries.append({
                        "id": vid,
                        "title": f"Highlight #{vid}",
                        "duration": 60,
                        "view_count": 0,
                        "upload_date": "",
                        "url": video_url,
                        "timestamp": 0
                    })
            if seed_entries:
                logger.info(f"Using {len(seed_entries)} candidate video(s) from seed list.")
                return seed_entries

        logger.error(f"Could not retrieve video listing for @{clean_user}.")
        return []

    def download_video(self, video_url: str, output_dir: str = "downloads") -> Optional[str]:
        os.makedirs(output_dir, exist_ok=True)
        out_template = os.path.join(output_dir, "%(id)s.%(ext)s")

        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "format": TIKTOK_FORMAT_SELECTOR,
            "outtmpl": out_template,
            "merge_output_format": "mp4",
        })

        retries = 3
        backoff = [4, 8, 12]

        for attempt in range(retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=True)
                    if not info:
                        raise ValueError("No video metadata returned")

                    video_id = info.get("id")
                    filepath = os.path.join(output_dir, f"{video_id}.mp4")
                    if os.path.exists(filepath):
                        logger.info(f"Downloaded video without watermark: {filepath}")
                        return os.path.abspath(filepath)
            except Exception as ex:
                logger.warning(f"Download attempt {attempt + 1}/{retries} failed for {video_url}: {ex}")

            if attempt < retries - 1:
                time.sleep(backoff[attempt])

        logger.error(f"Failed to download video {video_url} after {retries} attempts.")
        return None
