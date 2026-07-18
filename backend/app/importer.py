"""Parses a Meta ("Download Your Information") export and pulls out every
Instagram reel/post link it can find, along with the timestamp it was sent
and who sent it.

JSON exports (recommended - request your export in JSON format) are parsed
properly against Meta's message schema. A best-effort regex fallback handles
the HTML export format too, but timestamps aren't reliably recoverable from
HTML, so JSON is strongly preferred for correct ordering.
"""
import io
import json
import re
import zipfile
from urllib.parse import unquote

LINK_RE = re.compile(r"instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)")


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


def _extract_links(text: str) -> list[str]:
    if not text:
        return []
    decoded = unquote(text)
    return LINK_RE.findall(decoded)


def _iter_json_messages(data: dict):
    for message in data.get("messages", []):
        yield message


def _parse_message_json(data: dict) -> list[dict]:
    items = []
    for message in _iter_json_messages(data):
        sender = _fix_mojibake(message.get("sender_name", "")) or None
        sent_at_ms = message.get("timestamp_ms")

        shortcodes: set[str] = set()
        share = message.get("share")
        if isinstance(share, dict):
            shortcodes.update(_extract_links(share.get("link", "")))
            shortcodes.update(_extract_links(share.get("share_text", "")))

        # Fallback: scan every string value in the message for a link, in
        # case the schema differs (attachments, videos, content, etc).
        def scan(value):
            if isinstance(value, str):
                shortcodes.update(_extract_links(value))
            elif isinstance(value, dict):
                for v in value.values():
                    scan(v)
            elif isinstance(value, list):
                for v in value:
                    scan(v)

        scan(message)

        for shortcode in shortcodes:
            items.append(
                {
                    "shortcode": shortcode,
                    "url": _canonical(shortcode),
                    "sender": sender,
                    "sent_at_ms": sent_at_ms,
                }
            )
    return items


def _parse_html_fallback(html: str) -> list[dict]:
    items = []
    seen = set()
    for shortcode in LINK_RE.findall(unquote(html)):
        if shortcode in seen:
            continue
        seen.add(shortcode)
        items.append(
            {
                "shortcode": shortcode,
                "url": _canonical(shortcode),
                "sender": None,
                "sent_at_ms": None,
            }
        )
    return items


def parse_export(filename: str, content: bytes) -> list[dict]:
    """Parse a single uploaded file (which may itself be a zip of the whole
    export, a single message_*.json, or a message_*.html) and return a list
    of {shortcode, url, sender, sent_at_ms} dicts."""
    lower = filename.lower()

    if lower.endswith(".zip") or zipfile.is_zipfile(io.BytesIO(content)):
        return _parse_zip(content)

    if lower.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        return _parse_message_json(data)

    if lower.endswith(".html") or lower.endswith(".htm"):
        return _parse_html_fallback(content.decode("utf-8", errors="ignore"))

    # Unknown extension - try JSON, then fall back to raw text scan.
    try:
        data = json.loads(content.decode("utf-8"))
        return _parse_message_json(data)
    except Exception:
        return _parse_html_fallback(content.decode("utf-8", errors="ignore"))


def _parse_zip(content: bytes) -> list[dict]:
    items = []
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
                items.extend(_parse_message_json(data))
            elif lower.endswith(".html") or lower.endswith(".htm"):
                items.extend(
                    _parse_html_fallback(zf.read(name).decode("utf-8", errors="ignore"))
                )
    return items


def dedupe(items: list[dict]) -> list[dict]:
    by_shortcode: dict[str, dict] = {}
    for item in items:
        existing = by_shortcode.get(item["shortcode"])
        if existing is None:
            by_shortcode[item["shortcode"]] = item
        elif existing.get("sent_at_ms") is None and item.get("sent_at_ms") is not None:
            by_shortcode[item["shortcode"]] = item
    return list(by_shortcode.values())
