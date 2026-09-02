import os
import sys
import argparse
import logging
from dotenv import load_dotenv

from src.config import get_channel_by_id, load_config
from src.db import Database
from src.channel_runner import ChannelRunner

# Setup root logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("run")

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="TikTok to YouTube Shorts Automation Pipeline")
    parser.add_argument("--channel", type=str, required=True, help="Channel ID as defined in channels.yaml (e.g. pavlogameplayboy)")
    parser.add_argument("--slot", type=int, default=1, choices=[1, 2], help="Upload slot number (1 or 2)")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading to YouTube")
    parser.add_argument("--config", type=str, default="channels.yaml", help="Path to channels.yaml config file")
    parser.add_argument("--db-dir", type=str, default="data", help="Directory where channel SQLite DBs live")

    args = parser.parse_args()

    # Environment overrides for dry run
    if os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes"):
        args.dry_run = True

    try:
        cfg = get_channel_by_id(args.channel, config_path=args.config)
    except Exception as ex:
        logger.error(f"Failed to load channel config: {ex}")
        sys.exit(1)

    db_path = os.path.join(args.db_dir, f"{cfg.id}.db")
    db = Database(db_path=db_path)

    runner = ChannelRunner(config=cfg, db=db)
    success = runner.run_slot(slot=args.slot, dry_run=args.dry_run)

    # Checkpoint WAL
    try:
        db.checkpoint_wal()
    except Exception as ex:
        logger.warning(f"WAL checkpoint warning: {ex}")

    if not success:
        logger.error(f"Pipeline run for channel '{args.channel}' (Slot #{args.slot}) failed.")
        sys.exit(1)

    logger.info(f"Pipeline run for channel '{args.channel}' (Slot #{args.slot}) completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()
