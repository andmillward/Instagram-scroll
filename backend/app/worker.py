"""Background loop that keeps videos near the current playback position
pre-fetched, works through the rest of the backlog at a polite pace, and
evicts cached files that have fallen far behind the current position."""
import asyncio
import logging

from . import config, db
from .fetcher import FetchError, delete_cached_files, fetch_reel

log = logging.getLogger("worker")


def _pick_next_pending() -> dict | None:
    ids = db.ordered_ids()
    progress = db.get_progress()
    current_id = progress.get("current_reel_id")
    current_index = ids.index(current_id) if current_id in ids else 0

    window = ids[current_index : current_index + config.PREFETCH_WINDOW]
    for reel_id in window:
        reel = db.get_reel(reel_id)
        if reel and reel["status"] == "pending":
            return reel

    # Nothing urgent pending - work through the rest of the backlog,
    # oldest-first, starting from the current position and wrapping around.
    rest = ids[current_index + config.PREFETCH_WINDOW :] + ids[:current_index]
    for reel_id in rest:
        reel = db.get_reel(reel_id)
        if reel and reel["status"] == "pending":
            return reel

    return None


def _cleanup_cache():
    ids = db.ordered_ids()
    progress = db.get_progress()
    current_id = progress.get("current_reel_id")
    current_index = ids.index(current_id) if current_id in ids else 0

    stale_cutoff = current_index - config.CACHE_KEEP_BEHIND
    if stale_cutoff <= 0:
        return
    for reel_id in ids[:stale_cutoff]:
        reel = db.get_reel(reel_id)
        if reel and reel["status"] == "ready" and reel["local_path"]:
            delete_cached_files(reel["shortcode"])
            db.archive_reel(reel_id)


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
