import os
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class DiscordNotifier:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")

    def is_configured(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("https://discord.com/api/webhooks/"))

    def send_embed(self, title: str, description: str, color: int, fields: Optional[List[Dict[str, Any]]] = None) -> bool:
        if not self.is_configured():
            logger.info("Discord webhook not configured. Skipping notification.")
            return False

        payload = {
            "username": "TikTok → YouTube Automation Bot",
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "fields": fields or [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Automated YouTube Shorts Pipeline"}
                }
            ]
        }

        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code in (200, 204):
                return True
            else:
                logger.warning(f"Discord webhook failed with status {res.status_code}: {res.text}")
        except Exception as ex:
            logger.error(f"Error sending Discord webhook: {ex}")
        return False

    def notify_success(self, channel_id: str, slot: int, title: str, youtube_id: str, tiktok_url: str) -> None:
        fields = [
            {"name": "Slot", "value": f"Slot #{slot}", "inline": True},
            {"name": "YouTube Link", "value": f"[Watch Short](https://youtu.be/{youtube_id})", "inline": True},
            {"name": "Source TikTok", "value": f"[View Original]({tiktok_url})", "inline": True},
        ]
        self.send_embed(
            title=f"🚀 Uploaded: {channel_id} (Slot {slot})",
            description=f"**{title}**",
            color=0x2ECC71, # Green
            fields=fields
        )

    def notify_failure(self, channel_id: str, slot: int, error_msg: str, will_retry: bool = True) -> None:
        fields = [
            {"name": "Slot", "value": f"Slot #{slot}", "inline": True},
            {"name": "Status", "value": "Queued for retry (+90m / Tomorrow)" if will_retry else "Permanent Failure", "inline": True},
            {"name": "Error Detail", "value": f"```{error_msg[:500]}```", "inline": False}
        ]
        self.send_embed(
            title=f"⚠️ Upload Failed: {channel_id} (Slot {slot})",
            description="The automated run encountered an error.",
            color=0xE74C3C, # Red
            fields=fields
        )

    def notify_summary(self, channel_id: str, runs_today: int, successes: int, pending: int) -> None:
        fields = [
            {"name": "Total Runs", "value": str(runs_today), "inline": True},
            {"name": "Successful Uploads", "value": str(successes), "inline": True},
            {"name": "Pending Retries", "value": str(pending), "inline": True}
        ]
        self.send_embed(
            title=f"📊 Daily Summary: {channel_id}",
            description="24-hour channel upload report.",
            color=0x3498DB, # Blue
            fields=fields
        )
