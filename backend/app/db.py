import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

from . import config

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


@contextmanager
def _cursor():
    with _lock:
        conn = _get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()


def init_db():
    with _cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcode TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                sender TEXT,
                sent_at INTEGER,
                added_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                local_path TEXT,
                thumbnail_path TEXT,
                duration REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_reels_order ON reels (sent_at, id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_reel_id INTEGER,
                position_seconds REAL NOT NULL DEFAULT 0,
                updated_at INTEGER
            )
            """
        )
        cur.execute(
            "INSERT OR IGNORE INTO progress (id, current_reel_id, position_seconds) VALUES (1, NULL, 0)"
        )


def import_reels(items) -> dict:
    """items: iterable of dicts with shortcode, url, sender, sent_at_ms"""
    new = 0
    duplicate = 0
    now = int(time.time() * 1000)
    with _cursor() as cur:
        for item in items:
            try:
                cur.execute(
                    """
                    INSERT INTO reels (shortcode, url, sender, sent_at, added_at, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        item["shortcode"],
                        item["url"],
                        item.get("sender"),
                        item.get("sent_at_ms"),
                        now,
                    ),
                )
                new += 1
            except sqlite3.IntegrityError:
                duplicate += 1
    return {"new": new, "duplicate": duplicate}


def list_reels() -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, shortcode, url, sender, sent_at, status, duration, error
            FROM reels
            ORDER BY (sent_at IS NULL), sent_at ASC, id ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def get_reel(reel_id: int) -> Optional[dict]:
    with _cursor() as cur:
        cur.execute("SELECT * FROM reels WHERE id = ?", (reel_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_reel_by_shortcode(shortcode: str) -> Optional[dict]:
    with _cursor() as cur:
        cur.execute("SELECT * FROM reels WHERE shortcode = ?", (shortcode,))
        row = cur.fetchone()
        return dict(row) if row else None


def ordered_ids() -> list[int]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id FROM reels ORDER BY (sent_at IS NULL), sent_at ASC, id ASC"
        )
        return [row["id"] for row in cur.fetchall()]


def set_reel_fetching(reel_id: int):
    with _cursor() as cur:
        cur.execute("UPDATE reels SET status = 'fetching' WHERE id = ?", (reel_id,))


def set_reel_ready(reel_id: int, local_path: str, thumbnail_path: Optional[str], duration: Optional[float]):
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE reels
            SET status = 'ready', local_path = ?, thumbnail_path = ?, duration = ?, error = NULL
            WHERE id = ?
            """,
            (local_path, thumbnail_path, duration, reel_id),
        )


def set_reel_failed(reel_id: int, error: str, attempts: int):
    status = "failed" if attempts >= config.MAX_FETCH_ATTEMPTS else "pending"
    with _cursor() as cur:
        cur.execute(
            "UPDATE reels SET status = ?, attempts = ?, error = ? WHERE id = ?",
            (status, attempts, error, reel_id),
        )


def retry_reel(reel_id: int):
    with _cursor() as cur:
        cur.execute(
            "UPDATE reels SET status = 'pending', attempts = 0, error = NULL WHERE id = ?",
            (reel_id,),
        )


def archive_reel(reel_id: int):
    """Drop the cached file reference (used after cache cleanup deletes the file on disk)."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE reels SET status = 'pending', local_path = NULL, thumbnail_path = NULL WHERE id = ?",
            (reel_id,),
        )


def get_progress() -> dict:
    with _cursor() as cur:
        cur.execute("SELECT * FROM progress WHERE id = 1")
        return dict(cur.fetchone())


def set_progress(reel_id: int, position_seconds: float):
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE progress
            SET current_reel_id = ?, position_seconds = ?, updated_at = ?
            WHERE id = 1
            """,
            (reel_id, position_seconds, int(time.time())),
        )
