"""Resolves an Instagram reel URL to a locally-cached, directly-playable
video file using yt-dlp. No login/OAuth required for public reels; an
optional cookies.txt can be supplied (via config.COOKIES_FILE) for
private-account content.
"""
from pathlib import Path

import yt_dlp

from . import config


class FetchError(Exception):
    pass


def fetch_reel(url: str, shortcode: str) -> dict:
    """Downloads the reel's video (and a thumbnail) into config.CACHE_DIR.
    Returns {local_path, thumbnail_path, duration}. Raises FetchError on
    failure (private/deleted/blocked/etc)."""
    out_template = str(config.CACHE_DIR / f"{shortcode}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_template,
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "writethumbnail": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "socket_timeout": 30,
    }
    if config.COOKIES_FILE:
        ydl_opts["cookiefile"] = config.COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # yt-dlp raises its own exception types
        raise FetchError(str(exc)) from exc

    video_path = config.CACHE_DIR / f"{shortcode}.mp4"
    if not video_path.exists():
        # yt-dlp may have picked a different final extension.
        candidates = list(config.CACHE_DIR.glob(f"{shortcode}.*"))
        video_candidates = [p for p in candidates if p.suffix not in (".jpg", ".webp", ".png", ".json")]
        if not video_candidates:
            raise FetchError("download reported success but no video file was found")
        video_path = video_candidates[0]

    thumb_path = None
    for ext in (".jpg", ".webp", ".png"):
        candidate = config.CACHE_DIR / f"{shortcode}{ext}"
        if candidate.exists():
            thumb_path = candidate
            break

    return {
        "local_path": str(video_path),
        "thumbnail_path": str(thumb_path) if thumb_path else None,
        "duration": info.get("duration") if isinstance(info, dict) else None,
    }


def delete_cached_files(shortcode: str):
    for path in config.CACHE_DIR.glob(f"{shortcode}.*"):
        try:
            path.unlink()
        except OSError:
            pass
