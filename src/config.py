import os
import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

VALID_UPLOAD_MODES = {"popular_split", "short_only", "popular_only", "sequence"}

@dataclass
class ChannelConfig:
    id: str
    tiktok_username: str
    youtube_channel_name: str
    owner_email: str
    google_credentials_file: str
    oauth_token_file: str
    videos_per_day: int = 2
    description_footer: str = ""
    default_tags: List[str] = field(default_factory=list)
    youtube_category_id: str = "20"
    enabled: bool = True
    max_retry_days: int = 7
    shorts_max_seconds: int = 180
    upload_mode: str = "popular_split"
    max_download_candidates: int = 20
    tiktok_username_slot2: Optional[str] = None
    slot_publish_times_utc: Dict[int, str] = field(default_factory=dict)
    min_upload_date: Optional[str] = None
    fixed_title: Optional[str] = None

    def validate(self) -> None:
        if not self.id:
            raise ValueError("Channel ID cannot be empty.")
        if not self.tiktok_username:
            raise ValueError(f"Channel {self.id} must have a valid tiktok_username.")
        if self.upload_mode not in VALID_UPLOAD_MODES:
            raise ValueError(
                f"Invalid upload_mode '{self.upload_mode}' for channel {self.id}. "
                f"Must be one of {VALID_UPLOAD_MODES}"
            )
        if self.max_download_candidates < 5:
            self.max_download_candidates = 20


def load_config(config_path: str = "channels.yaml") -> List[ChannelConfig]:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    if not raw_data or "channels" not in raw_data:
        raise ValueError(f"Invalid {config_path}: Missing 'channels' list.")

    channels: List[ChannelConfig] = []
    for item in raw_data["channels"]:
        cfg = ChannelConfig(
            id=item["id"],
            tiktok_username=item.get("tiktok_username", "").lstrip("@"),
            youtube_channel_name=item.get("youtube_channel_name", item["id"]),
            owner_email=item.get("owner_email", ""),
            google_credentials_file=item.get("google_credentials_file", f"credentials/{item['id']}_client_secret.json"),
            oauth_token_file=item.get("oauth_token_file", f"tokens/{item['id']}_token.json"),
            videos_per_day=item.get("videos_per_day", 2),
            description_footer=item.get("description_footer", ""),
            default_tags=item.get("default_tags", []),
            youtube_category_id=str(item.get("youtube_category_id", "20")),
            enabled=item.get("enabled", True),
            max_retry_days=item.get("max_retry_days", 7),
            shorts_max_seconds=item.get("shorts_max_seconds", 180),
            upload_mode=item.get("upload_mode", "popular_split"),
            max_download_candidates=item.get("max_download_candidates", 20),
            tiktok_username_slot2=item.get("tiktok_username_slot2"),
            slot_publish_times_utc={int(k): v for k, v in item.get("slot_publish_times_utc", {}).items()},
            min_upload_date=item.get("min_upload_date"),
            fixed_title=item.get("fixed_title")
        )
        cfg.validate()
        channels.append(cfg)

    return channels


def get_channel_by_id(channel_id: str, config_path: str = "channels.yaml") -> ChannelConfig:
    channels = load_config(config_path)
    for ch in channels:
        if ch.id == channel_id:
            return ch
    raise ValueError(f"Channel with ID '{channel_id}' not found in {config_path}")
