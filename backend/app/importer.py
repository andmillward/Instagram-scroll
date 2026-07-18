"""Parses a Meta ("Download Your Information") export and pulls out:

- every Instagram reel/post link ("reels"), with the timestamp it was sent
  and who sent it
- every other message with meaningful content ("notes") - plain text
  captions, and links to anything else (Threads posts, articles, etc) -
  so that context doesn't just get silently dropped.

JSON exports (recommended - request your export in JSON format) are parsed
properly against Meta's message schema. A best-effort regex fallback handles
the HTML export format too, but timestamps aren't reliably recoverable from
HTML (and notes aren't extracted at all from HTML), so JSON is strongly
preferred.
"""
import hashlib
import io
import json
import re
import zipfile
from urllib.parse import parse_qs, unquote, urlparse

REEL_RE = re.compile(r"instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

REDIRECT_HOSTS = {"l.instagram.com", "l.facebook.com", "lm.facebook.com", "l.messenger.com"}


def _fix_mojibake(s: str) -> str:
    """Meta's JSON export mis-encodes non-ASCII text as UTF-8-bytes-stored-as-
    Latin-1. This undoes it; falls back to the original string if it doesn't
    apply."""
    if not s:
        return s
    try:
        return s.encode("latin1").decode("utf8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _canonical(shortcode: str) -> str:
    return f"https://www.instagram.com/reel/{shortcode}/"


def _extract_shortcodes(text: str) -> list[str]:
    if not text:
        return []
    return REEL_RE.findall(unquote(text))


def _resolve_redirect(url: str) -> str:
    """Unwraps Meta's l.instagram.com/lm.facebook.com click-tracking
    redirects to the actual destination URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.netloc in REDIRECT_HOSTS:
        qs = parse_qs(parsed.query)
        if qs.get("u"):
            return qs["u"][0]
    return url


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    decoded = unquote(text)
    seen = set()
    out = []
    for raw in URL_RE.findall(decoded):
        cleaned = raw.rstrip(".,;:!?")
        resolved = _resolve_redirect(cleaned)
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _caption_text(content: str) -> str | None:
    """Returns the sender's own caption typed alongside a shared reel, or
    None if there's nothing beyond the link itself (e.g. content is just the
    share URL Instagram already filled in)."""
    if not content or not content.strip():
        return None
    without_urls = URL_RE.sub("", unquote(content)).strip()
    return content.strip() if without_urls else None


def _note_key(sender: str, sent_at_ms, text: str, links: list[str]) -> str:
    raw = f"{sender}|{sent_at_ms}|{text}|{'|'.join(links)}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def _iter_json_messages(data: dict):
    for message in data.get("messages", []):
        yield message


def _parse_message_json(data: dict) -> dict:
    reels = []
    notes = []

    for message in _iter_json_messages(data):
        sender = _fix_mojibake(message.get("sender_name", "")) or None
        sent_at_ms = message.get("timestamp_ms")
        content = _fix_mojibake(message.get("content", "")) or ""
        share = message.get("share")
        share_link = share.get("link", "") if isinstance(share, dict) else ""
        share_text = _fix_mojibake(share.get("share_text", "")) if isinstance(share, dict) else ""

        shortcodes: set[str] = set()
        shortcodes.update(_extract_shortcodes(share_link))
        shortcodes.update(_extract_shortcodes(share_text))
        shortcodes.update(_extract_shortcodes(content))

        if shortcodes:
            # Represented as reel(s); any caption typed alongside the share
            # travels with the reel itself rather than becoming a separate
            # note (so it doesn't get silently dropped or shown far away
            # from the video it's actually about).
            caption = _caption_text(content)
            for shortcode in shortcodes:
                reels.append(
                    {
                        "shortcode": shortcode,
                        "url": _canonical(shortcode),
                        "sender": sender,
                        "sent_at_ms": sent_at_ms,
                        "caption": caption,
                    }
                )
            continue

        text = content.strip()
        links = _extract_urls(share_link) + _extract_urls(share_text) + _extract_urls(content)
        # de-dup while preserving order
        links = list(dict.fromkeys(links))
        if not text and share_text.strip():
            text = share_text.strip()

        if not text and not links:
            continue  # nothing worth surfacing (sticker, reaction, photo-only, etc)

        notes.append(
            {
                "message_key": _note_key(sender, sent_at_ms, text, links),
                "sender": sender,
                "sent_at_ms": sent_at_ms,
                "text": text,
                "links": links,
            }
        )

    return {"reels": reels, "notes": notes}


def _parse_html_fallback(html: str) -> dict:
    reels = []
    seen = set()
    for shortcode in REEL_RE.findall(unquote(html)):
        if shortcode in seen:
            continue
        seen.add(shortcode)
        reels.append(
            {
                "shortcode": shortcode,
                "url": _canonical(shortcode),
                "sender": None,
                "sent_at_ms": None,
                "caption": None,
            }
        )
    return {"reels": reels, "notes": []}


def parse_export(filename: str, content: bytes) -> dict:
    """Parse a single uploaded file (which may itself be a zip of the whole
    export, a single message_*.json, or a message_*.html) and return
    {"reels": [...], "notes": [...]}."""
    lower = filename.lower()

    if lower.endswith(".zip") or zipfile.is_zipfile(io.BytesIO(content)):
        return _parse_zip(content)

    if lower.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"reels": [], "notes": []}
        return _parse_message_json(data)

    if lower.endswith(".html") or lower.endswith(".htm"):
        return _parse_html_fallback(content.decode("utf-8", errors="ignore"))

    # Unknown extension - try JSON, then fall back to raw text scan.
    try:
        data = json.loads(content.decode("utf-8"))
        return _parse_message_json(data)
    except Exception:
        return _parse_html_fallback(content.decode("utf-8", errors="ignore"))


def _parse_zip(content: bytes) -> dict:
    reels = []
    notes = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if "/messages/" not in lower and not lower.startswith("messages/"):
                continue
            if lower.endswith(".json"):
                try:
                    data = json.loads(zf.read(name).decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                parsed = _parse_message_json(data)
            elif lower.endswith(".html") or lower.endswith(".htm"):
                parsed = _parse_html_fallback(zf.read(name).decode("utf-8", errors="ignore"))
            else:
                continue
            reels.extend(parsed["reels"])
            notes.extend(parsed["notes"])
    return {"reels": reels, "notes": notes}


def dedupe_reels(items: list[dict]) -> list[dict]:
    by_shortcode: dict[str, dict] = {}
    for item in items:
        existing = by_shortcode.get(item["shortcode"])
        if existing is None:
            by_shortcode[item["shortcode"]] = item
            continue
        merged = dict(existing)
        if merged.get("sent_at_ms") is None and item.get("sent_at_ms") is not None:
            merged["sent_at_ms"] = item["sent_at_ms"]
            merged["sender"] = item.get("sender")
        if not merged.get("caption") and item.get("caption"):
            merged["caption"] = item["caption"]
        by_shortcode[item["shortcode"]] = merged
    return list(by_shortcode.values())


def dedupe_notes(items: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for item in items:
        by_key.setdefault(item["message_key"], item)
    return list(by_key.values())
