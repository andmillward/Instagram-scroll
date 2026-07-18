"""Minimal HTTP Range support for serving cached video files, so seeking and
TV/Chromecast playback both work reliably regardless of which Starlette
version is in the image."""
import os
import re

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _iter_range(path: str, start: int, end: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def range_file_response(request: Request, path: str, media_type: str) -> Response:
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range")

    if range_header is None:
        return StreamingResponse(
            _iter_range(path, 0, file_size - 1),
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )

    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not match:
        return Response(status_code=416)

    start_s, end_s = match.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)

    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(
        _iter_range(path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )
