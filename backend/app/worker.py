"""Background loop that keeps videos near the current playback position
pre-fetched, works through the rest of the backlog at a polite pace, and
evicts cached files that have fallen far behind the current position.

"Position" is tracked over the merged reel+notes timeline (see db.py's
build_timeline), but only reel entries need fetching/eviction - notes
entries are skipped when counting how far ahead/behind to look."""
import asyncio
import logging

from . import config, db
from .fetcher import FetchError, delete_cached_files, fetch_reel

log = logging.getLogger("worker")


def _current_index(timeline: list[dict]) -> int:
    progress = db.get_progress()
    key = progress.get("current_key")
    if key:
        for i, item in enumerate(timeline):
            if item["key"] == key:
                return i
    return 0


def _pick_next_pending() -> dict | None:
    timeline = db.build_timeline()
    if not timeline:
        return None
    idx = _current_index(timeline)

    # Priority: the next PREFETCH_WINDOW reel entries from the current
    # position onward.
    seen = 0
    for item in timeline[idx:]:
        if item["kind"] != "reel":
            continue
        seen += 1
        if item["status"] == "pending":
            return db.get_reel(item["id"])
        if seen >= config.PREFETCH_WINDOW:
            break

    # Otherwise, work through the rest of the backlog (forward, then wrap
    # around to the start) at a low priority.
    for item in timeline[idx:] + timeline[:idx]:
        if item["kind"] == "reel" and item["status"] == "pending":
            return db.get_reel(item["id"])

    return None


def _cleanup_cache():
    timeline = db.build_timeline()
    if not timeline:
        return
    idx = _current_index(timeline)

    seen = 0
    for item in reversed(timeline[:idx]):
        if item["kind"] != "reel":
            continue
        seen += 1
        if seen <= config.CACHE_KEEP_BEHIND:
            continue
        if item["status"] == "ready" and item.get("local_path"):
            delete_cached_files(item["shortcode"])
            db.archive_reel(item["id"])


async def _fetch_one(reel: dict):
    db.set_reel_fetching(reel["id"])
    try:
        result = await asyncio.to_thread(fetch_reel, reel["url"], reel["shortcode"])
        db.set_reel_ready(
            reel["id"], result["local_path"], result["thumbnail_path"], result["duration"]
        )
        log.info("fetched %s (%s)", reel["shortcode"], reel["url"])
    except FetchError as exc:
        attempts = (reel.get("attempts") or 0) + 1
        db.set_reel_failed(reel["id"], str(exc), attempts)
        log.warning("failed to fetch %s: %s (attempt %d)", reel["shortcode"], exc, attempts)


async def run_worker():
    while True:
        try:
            _cleanup_cache()
            reel = await asyncio.to_thread(_pick_next_pending)
            if reel is None:
                await asyncio.sleep(config.IDLE_POLL_SECONDS)
                continue
            await _fetch_one(reel)
            await asyncio.sleep(config.FETCH_DELAY_SECONDS)
        except Exception:
            log.exception("worker loop iteration failed")
            await asyncio.sleep(config.IDLE_POLL_SECONDS)
