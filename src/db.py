import sqlite3
import os
from datetime import datetime, timezone
from typing import Set, Optional, Dict, Any, List

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for concurrency and durability
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posted_videos (
                    tiktok_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    youtube_id TEXT,
                    title TEXT,
                    status TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    next_retry_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_posted_channel_status 
                ON posted_videos (channel_id, status);
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    run_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    video_id TEXT,
                    message TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_date_slot 
                ON runs (channel_id, run_date, slot);
            """)
            conn.commit()

    def is_slot_already_ran_today(self, channel_id: str, slot: int, run_date: Optional[str] = None) -> bool:
        if run_date is None:
            run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM runs 
                WHERE channel_id = ? AND slot = ? AND run_date = ? AND status = 'success'
                LIMIT 1;
            """, (channel_id, slot, run_date))
            return cursor.fetchone() is not None

    def get_posted_ids(self, channel_id: str) -> Set[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tiktok_id FROM posted_videos 
                WHERE channel_id = ? AND status IN ('uploaded', 'failed_permanent', 'skipped', 'pending_retry');
            """, (channel_id,))
            return {row["tiktok_id"] for row in cursor.fetchall()}

    def get_pending_retries(self, channel_id: str, today_str: Optional[str] = None) -> List[sqlite3.Row]:
        if today_str is None:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM posted_videos 
                WHERE channel_id = ? AND status = 'pending_retry' AND (next_retry_date IS NULL OR next_retry_date <= ?)
                ORDER BY created_at ASC;
            """, (channel_id, today_str))
            return cursor.fetchall()

    def record_posted_video(
        self,
        tiktok_id: str,
        channel_id: str,
        status: str,
        youtube_id: Optional[str] = None,
        title: Optional[str] = None,
        retry_count: int = 0,
        next_retry_date: Optional[str] = None
    ) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO posted_videos (
                    tiktok_id, channel_id, youtube_id, title, status, retry_count, next_retry_date, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tiktok_id) DO UPDATE SET
                    youtube_id = excluded.youtube_id,
                    title = COALESCE(excluded.title, posted_videos.title),
                    status = excluded.status,
                    retry_count = excluded.retry_count,
                    next_retry_date = excluded.next_retry_date,
                    updated_at = excluded.updated_at;
            """, (tiktok_id, channel_id, youtube_id, title, status, retry_count, next_retry_date, now_str, now_str))
            conn.commit()

    def record_run(
        self,
        channel_id: str,
        slot: int,
        status: str,
        video_id: Optional[str] = None,
        message: Optional[str] = None,
        run_date: Optional[str] = None
    ) -> None:
        if run_date is None:
            run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO runs (channel_id, slot, run_date, status, video_id, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (channel_id, slot, run_date, status, video_id, message, now_str))
            conn.commit()

    def checkpoint_wal(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
