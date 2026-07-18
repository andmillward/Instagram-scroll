import json
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


def _column_names(cur, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}


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
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_key TEXT UNIQUE NOT NULL,
                sender TEXT,
                sent_at INTEGER,
                text TEXT,
                links TEXT NOT NULL DEFAULT '[]',
                added_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notes_order ON notes (sent_at, id)"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_key TEXT,
                position_seconds REAL NOT NULL DEFAULT 0,
                updated_at INTEGER
            )
            """
        )

        # Migration from the earlier schema (current_reel_id INTEGER).
        progress_cols = _column_names(cur, "progress")
        if "current_key" not in progress_cols:
            cur.execute("ALTER TABLE progress ADD COLUMN current_key TEXT")
        if "current_reel_id" in progress_cols:
            cur.execute(
                """
                UPDATE progress SET current_key = 'reel:' || current_reel_id
                WHERE current_key IS NULL AND current_reel_id IS NOT NULL
                """
            )

        cur.execute(
            "INSERT OR IGNORE INTO progress (id, current_key, position_seconds) VALUES (1, NULL, 0)"
        )


# --- Reels -----------------------------------------------------------------

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


# --- Notes -------------------------------------------------------------------

def import_notes(items) -> dict:
    """items: iterable of dicts with message_key, sender, sent_at_ms, text, links"""
    new = 0
    duplicate = 0
    now = int(time.time() * 1000)
    with _cursor() as cur:
        for item in items:
            try:
                cur.execute(
                    """
                    INSERT INTO notes (message_key, sender, sent_at, text, links, added_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["message_key"],
                        item.get("sender"),
                        item.get("sent_at_ms"),
                        item.get("text") or "",
                        json.dumps(item.get("links") or []),
                        now,
                    ),
                )
                new += 1
            except sqlite3.IntegrityError:
                duplicate += 1
    return {"new": new, "duplicate": duplicate}


def list_notes() -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, sender, sent_at, text, links
            FROM notes
            ORDER BY (sent_at IS NULL), sent_at ASC, id ASC
            """
        )
        out = []
        for row in cur.fetchall():
            d = dict(row)
            d["links"] = json.loads(d["links"] or "[]")
            out.append(d)
        return out


def get_note(note_id: int) -> Optional[dict]:
    with _cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["links"] = json.loads(d["links"] or "[]")
        return d


# --- Timeline (reels + notes merged chronologically) ------------------------

def build_timeline() -> list[dict]:
    """Merges reels and notes in chronological order, and groups consecutive
    non-reel notes into a single interstitial block. Each returned item has
    a "kind" ("reel" or "notes") and a unique "key" for progress tracking."""
    reels = list_reels()
    notes = list_notes()

    tagged = [("reel", r["sent_at"], r) for r in reels] + [("note", n["sent_at"], n) for n in notes]
    tagged.sort(key=lambda t: (t[1] is None, t[1] if t[1] is not None else 0))

    timeline: list[dict] = []
    pending_notes: list[dict] = []

    def flush():
        nonlocal pending_notes
        if pending_notes:
            first = pending_notes[0]
            timeline.append(
                {
                    "kind": "notes",
                    "key": f"notes:{first['id']}",
                    "sent_at": first["sent_at"],
                    "messages": pending_notes,
                }
            )
            pending_notes = []

    for kind, _sent_at, obj in tagged:
        if kind == "reel":
            flush()
            timeline.append({**obj, "kind": "reel", "key": f"reel:{obj['id']}"})
        else:
            pending_notes.append(obj)
    flush()

    return timeline


# --- Progress -----------------------------------------------------------------

def get_progress() -> dict:
    with _cursor() as cur:
        cur.execute("SELECT * FROM progress WHERE id = 1")
        return dict(cur.fetchone())


def set_progress(key: str, position_seconds: float):
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE progress
            SET current_key = ?, position_seconds = ?, updated_at = ?
            WHERE id = 1
            """,
            (key, position_seconds, int(time.time())),
        )
