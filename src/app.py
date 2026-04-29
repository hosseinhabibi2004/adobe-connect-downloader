import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import redis
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import config
from src.utils.converter import convert_meeting


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


logger = logging.getLogger(__name__)


try:
    redis_client = redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )
    redis_client.ping()
except redis.ConnectionError as exc:
    msg = "Could not connect to Redis. Please ensure Redis is running."
    raise RuntimeError(msg) from exc

app = FastAPI()

# Mount static files (CSS/JS)
app.mount(
    "/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static"
)


def get_job_key(job_id: str) -> str:
    return f"job:{job_id}"


def cleanup_expired_jobs() -> None:
    """
    Removes jobs from Redis if the output file no longer exists.
    This keeps the history relevant and saves memory.
    """
    keys = redis_client.keys("job:*")
    for key in keys:
        meeting_id = key.replace("job:", "")
        output_file = config.OUTPUT_DIR / f"{meeting_id}.mkv"

        if not output_file.exists():
            # File is gone, so we consider this job "stale" or "cleaned up"
            # We remove it from cache
            redis_client.delete(key)


# SSE Endpoint for real-time updates without polling
@app.get("/sse/{meeting_id}")
async def event_stream(meeting_id: str, request: Request) -> StreamingResponse:
    job_key = get_job_key(meeting_id)

    async def event_generator() -> AsyncGenerator:
        last_data = None

        while not await request.is_disconnected():
            # Read current state from Redis
            current_data_raw = redis_client.get(job_key)

            if current_data_raw:
                current_data = json.loads(current_data_raw)

                # Send update only if data changed
                if current_data != last_data:
                    last_data = current_data
                    yield f"data: {json.dumps(current_data)}\n\n"

            await asyncio.sleep(0.5)  # 500ms polling interval for SSE

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def make_progress_callback(job_id: str) -> callable[[str, float, str], None]:
    def callback(stage: str, progress: float, message: str) -> None:
        try:
            data = {
                "stage": stage,
                "progress": progress,
                "message": message,
                "timestamp": datetime.now(config.TIMEZONE).isoformat(),
            }
            redis_client.setex(f"job:{job_id}", 86400, json.dumps(data))
        except Exception:  # noqa: BLE001, S110
            pass  # Fail silently if Redis goes down during callback

    return callback


def build_download_link(meeting_url: str) -> tuple[str, str]:
    parsed = urlparse(meeting_url)
    query = parse_qs(parsed.query)

    base_path = parsed.path.rstrip("/")
    meeting_id = base_path.split("/")[-1]
    download_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/output/{meeting_id}.zip?download=zip"

    if "session" in query:
        session_id = query["session"][0]
        download_url += f"&session={session_id}"

    return download_url, meeting_id


def download_zip(
    download_url: str, meeting_id: str, callback: callable[[str, float, str], None]
) -> Path:
    path = config.TEMP_DIR / f"{meeting_id}.zip"

    if path.exists():
        return path

    response = requests.get(download_url, stream=True)  # noqa: S113
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "zip" not in content_type and "application/zip" not in content_type:
        if "You do not have permission to access this item." in response.text:
            msg = "شما دسترسی لازم برای دانلود این جلسه را ندارید."
            raise PermissionError(msg)

        msg = "مشکلی در دانلود پیش آمده است. لطفاً لینک خود را بررسی نمایید."
        raise ValueError(msg)

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    with path.open("wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)
                downloaded += len(chunk)

                progress = downloaded / total_size if total_size else 0

                callback("download", progress, "در حال دانلود جلسه...")

    callback("download", 1.0, "دانلود به اتمام رسید.")

    return path


def process_meeting(
    download_url: str, meeting_id: str, callback: callable[[str, float, str], None]
) -> None:
    try:
        download_zip(download_url, meeting_id, callback)
        convert_meeting(meeting_id, callback)
    except Exception as e:
        msg = f"Error processing meeting {meeting_id} ({download_url})"
        logger.exception(msg)
        callback("error", 1, str(e))


@app.post("/convert")
def convert(meeting_url: str) -> dict:
    cleanup_expired_jobs()

    download_url, meeting_id = build_download_link(meeting_url)

    job_key = get_job_key(meeting_id)
    path = config.OUTPUT_DIR / f"{meeting_id}.mkv"
    existing = redis_client.get(job_key)

    if path.exists() or existing:
        return {
            "status": "success",
            "download_url": f"/download/{meeting_id}",
            "sse_url": f"/sse/{meeting_id}",
            "existing": True,
        }

    callback = make_progress_callback(meeting_id)

    thread = threading.Thread(
        target=process_meeting, args=(download_url, meeting_id, callback)
    )

    thread.start()

    return {
        "status": "success",
        "download_url": f"/download/{meeting_id}",
        "sse_url": f"/sse/{meeting_id}",
        "existing": False,
    }


@app.get("/download/{meeting_id}")
def download_file(meeting_id: str) -> FileResponse:
    file_path = config.OUTPUT_DIR / f"{meeting_id}.mkv"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")

    return FileResponse(
        file_path,
        media_type="video/x-matroska",
        filename=f"{meeting_id}.mkv",
    )


# New Endpoint: Retrieve history for the frontend
@app.get("/history")
def get_history() -> list:
    # Clean up any jobs where file is missing before returning history
    cleanup_expired_jobs()

    keys = redis_client.keys("job:*")
    history = []
    for key in keys:
        job_data = redis_client.get(key)
        if job_data:
            try:
                data = json.loads(job_data)
                meeting_id = key.replace("job:", "")
                history.append(
                    {
                        "meeting_id": meeting_id,
                        "stage": data.get("stage", ""),
                        "progress": data.get("progress", 0),
                        "message": data.get("message", ""),
                        "timestamp": data.get("timestamp", ""),
                    }
                )
            except json.JSONDecodeError:
                continue

    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return history


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.BASE_DIR / "templates" / "index.html")
