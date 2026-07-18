import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db
from .importer import dedupe_notes, dedupe_reels, parse_export
from .streaming import range_file_response
from .worker import run_worker

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(run_worker())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(lifespan=lifespan)


class ProgressUpdate(BaseModel):
    key: str
    position_seconds: float = 0


@app.post("/api/import")
async def import_export(files: list[UploadFile]):
    all_reels = []
    all_notes = []
    for f in files:
        content = await f.read()
        parsed = parse_export(f.filename, content)
        all_reels.extend(parsed["reels"])
        all_notes.extend(parsed["notes"])

    reels = dedupe_reels(all_reels)
    notes = dedupe_notes(all_notes)
    reel_result = db.import_reels(reels)
    note_result = db.import_notes(notes)
    return {
        "found": len(reels) + len(notes),
        "new": reel_result["new"] + note_result["new"],
        "duplicate": reel_result["duplicate"] + note_result["duplicate"],
        "reels_found": len(reels),
        "notes_found": len(notes),
    }


@app.get("/api/timeline")
async def get_timeline():
    return db.build_timeline()


@app.get("/api/reels")
async def get_reels():
    return db.list_reels()


@app.get("/api/reels/{reel_id}")
async def get_reel_one(reel_id: int):
    reel = db.get_reel(reel_id)
    if reel is None:
        raise HTTPException(404, "no such reel")
    return reel


@app.get("/api/progress")
async def get_progress():
    return db.get_progress()


@app.post("/api/progress")
async def post_progress(update: ProgressUpdate):
    try:
        if update.key.startswith("reel:"):
            found = db.get_reel(int(update.key[len("reel:"):])) is not None
        elif update.key.startswith("notes:"):
            found = db.get_note(int(update.key[len("notes:"):])) is not None
        else:
            raise HTTPException(400, "invalid key")
    except ValueError:
        raise HTTPException(400, "invalid key")
    if not found:
        raise HTTPException(404, "no such item")
    db.set_progress(update.key, update.position_seconds)
    return {"ok": True}


@app.post("/api/reels/{reel_id}/retry")
async def retry_reel(reel_id: int):
    reel = db.get_reel(reel_id)
    if reel is None:
        raise HTTPException(404, "no such reel")
    db.retry_reel(reel_id)
    return {"ok": True}


@app.get("/api/video/{shortcode}")
async def get_video(shortcode: str, request: Request):
    reel = db.get_reel_by_shortcode(shortcode)
    if reel is None or reel["status"] != "ready" or not reel["local_path"]:
        raise HTTPException(404, "not ready")
    media_type = mimetypes.guess_type(reel["local_path"])[0] or "video/mp4"
    return range_file_response(request, reel["local_path"], media_type)


@app.get("/api/thumb/{shortcode}")
async def get_thumb(shortcode: str):
    reel = db.get_reel_by_shortcode(shortcode)
    if reel is None or not reel["thumbnail_path"]:
        raise HTTPException(404, "no thumbnail")
    return FileResponse(reel["thumbnail_path"])


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse({"detail": "not found"}, status_code=404)


if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
