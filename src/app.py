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


main_redis_client = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB,
    password=config.REDIS_PASSWORD,
    decode_responses=True,
)
main_redis_client.ping()


def get_thread_safe_redis_client() -> redis.Redis:
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )


app = FastAPI()

app.mount(
    "/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static"
)


def get_job_key(job_id: str) -> str:
    return f"job:{job_id}"


def get_pub_sub_channel(job_id: str) -> str:
    return f"updates:{job_id}"


def get_user_history_key(user_id: str) -> str:
    return f"user_history:{user_id}"


def cleanup_expired_jobs(client: redis.Redis | None = None) -> None:
    r_client = client if client else main_redis_client
    keys = r_client.keys("job:*")
    for key in keys:
        meeting_id = key.replace("job:", "")
        output_file = config.OUTPUT_DIR / f"{meeting_id}.mkv"
        if not output_file.exists():
            r_client.delete(key)


def add_to_user_history(
    user_id: str, meeting_id: str, client: redis.Redis | None = None
) -> None:
    r_client = client if client else main_redis_client
    history_key = get_user_history_key(user_id)

    existing_items = r_client.lrange(history_key, 0, -1)
    if meeting_id not in existing_items:
        r_client.lpush(history_key, meeting_id)
        r_client.ltrim(history_key, 0, 99)


def remove_from_user_history(
    user_id: str, meeting_id: str, client: redis.Redis | None = None
) -> None:
    r_client = client if client else main_redis_client
    history_key = get_user_history_key(user_id)
    r_client.lrem(history_key, 0, meeting_id)


@app.get("/sse/{meeting_id}")
async def event_stream(meeting_id: str, request: Request) -> StreamingResponse:
    job_key = get_job_key(meeting_id)
    channel_name = get_pub_sub_channel(meeting_id)

    async def event_generator() -> AsyncGenerator:
        try:
            current_data_raw = main_redis_client.get(job_key)
            if current_data_raw:
                data = json.loads(current_data_raw)
                yield f"data: {json.dumps(data)}\n\n"
        except Exception:  # noqa: BLE001, S110
            pass

        pubsub = main_redis_client.pubsub()
        pubsub.subscribe(channel_name)

        try:
            while not await request.is_disconnected():
                message = pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield f"data: {json.dumps(data)}\n\n"
                    except json.JSONDecodeError:
                        pass
        finally:
            pubsub.unsubscribe(channel_name)
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def make_progress_callback(job_id: str) -> callable[[str, float, str], None]:
    channel_name = get_pub_sub_channel(job_id)
    thread_client = get_thread_safe_redis_client()

    def callback(stage: str, progress: float, message: str) -> None:
        try:
            if stage == "error":
                progress = 1.0

            data = {
                "stage": stage,
                "progress": progress,
                "message": message,
                "timestamp": datetime.now(config.TIMEZONE).isoformat(),
            }
            thread_client.setex(f"job:{job_id}", 86400, json.dumps(data))
            thread_client.publish(channel_name, json.dumps(data))
        except Exception as exc:
            msg = f"Callback failed for job {job_id}: {exc}"
            logger.exception(msg)

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

    try:
        response = requests.get(download_url, stream=True, timeout=300)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        callback("error", 1.0, f"Network error during download: {exc!s}")
        return path

    content_type = response.headers.get("content-type", "")
    if "zip" not in content_type and "application/zip" not in content_type:
        if "You do not have permission to access this item." in response.text:
            msg = "شما دسترسی لازم برای دانلود این جلسه را ندارید."
            callback("error", 1.0, msg)
            return path

        msg = "مشکلی در دانلود پیش آمده است. لطفاً لینک خود را بررسی نمایید."
        callback("error", 1.0, msg)
        return path

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    try:
        with path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
                    downloaded += len(chunk)
                    progress = downloaded / total_size if total_size else 0
                    callback("download", progress, "در حال دانلود جلسه...")
    except Exception as exc:
        callback("error", 1.0, f"Disk error during download: {exc!s}")
        raise exc from None

    callback("download", 1.0, "دانلود به اتمام رسید.")
    return path


def process_meeting(
    download_url: str, meeting_id: str, callback: callable[[str, float, str], None]
) -> None:
    try:
        get_job_key(meeting_id)
        output_file = config.OUTPUT_DIR / f"{meeting_id}.mkv"

        if output_file.exists():
            callback("finalize", 1.0, "فایل خروجی موجود است.")
            return

        zip_path = download_zip(download_url, meeting_id, callback)

        if not zip_path.exists():
            return

        convert_meeting(meeting_id, callback)

        if not output_file.exists():
            callback("error", 1.0, "فایل نهایی ایجاد نشد.")

    except Exception as exc:
        msg = f"Unexpected error in process_meeting for {meeting_id}: {exc!s}"
        logger.exception(msg)
        callback("error", 1.0, msg)


@app.post("/convert")
def convert(meeting_url: str, user_id: str = "default_user") -> dict:
    cleanup_expired_jobs(main_redis_client)

    try:
        download_url, meeting_id = build_download_link(meeting_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {exc!s}") from exc

    job_key = get_job_key(meeting_id)
    path = config.OUTPUT_DIR / f"{meeting_id}.mkv"

    if path.exists():
        add_to_user_history(user_id, meeting_id, main_redis_client)

        callback = make_progress_callback(meeting_id)
        callback("finalize", 1.0, "فایل خروجی موجود است.")

        return {
            "status": "success",
            "download_url": f"/download/{meeting_id}",
            "sse_url": f"/sse/{meeting_id}",
            "existing": True,
            "file_ready": True,
        }

    existing = main_redis_client.get(job_key)
    if existing:
        add_to_user_history(user_id, meeting_id, main_redis_client)

        return {
            "status": "success",
            "download_url": f"/download/{meeting_id}",
            "sse_url": f"/sse/{meeting_id}",
            "existing": True,
            "file_ready": False,
        }

    add_to_user_history(user_id, meeting_id, main_redis_client)

    callback = make_progress_callback(meeting_id)

    callback("download", 0.0, "شروع دانلود...")

    thread = threading.Thread(
        target=process_meeting,
        args=(download_url, meeting_id, callback),
        daemon=True,
    )

    thread.start()

    return {
        "status": "success",
        "download_url": f"/download/{meeting_id}",
        "sse_url": f"/sse/{meeting_id}",
        "existing": False,
        "file_ready": False,
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


@app.get("/history")
def get_history(user_id: str = "default_user") -> list:
    main_redis_client.ping()
    cleanup_expired_jobs(main_redis_client)

    history_key = get_user_history_key(user_id)
    meeting_ids = main_redis_client.lrange(history_key, 0, -1)

    history = []
    for meeting_id in meeting_ids:
        job_key = get_job_key(meeting_id)
        output_file = config.OUTPUT_DIR / f"{meeting_id}.mkv"

        try:
            job_data = main_redis_client.get(job_key)
            if job_data:
                data = json.loads(job_data)
                history.append(
                    {
                        "meeting_id": meeting_id,
                        "stage": data.get("stage", ""),
                        "progress": data.get("progress", 0),
                        "message": data.get("message", ""),
                        "timestamp": data.get("timestamp", ""),
                    }
                )
            elif output_file.exists():
                history.append(
                    {
                        "meeting_id": meeting_id,
                        "stage": "finalize",
                        "progress": 1.0,
                        "message": "آماده",
                        "timestamp": datetime.fromtimestamp(
                            output_file.stat().st_mtime, tz=config.TIMEZONE
                        ).isoformat(),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            msg = f"Error reading job {meeting_id}: {exc}"
            logger.warning(msg)
            continue

    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return history


@app.delete("/history/{meeting_id}")
def delete_history_item(meeting_id: str, user_id: str = "default_user") -> dict:
    remove_from_user_history(user_id, meeting_id, main_redis_client)
    return {"status": "success", "message": "آیتم از تاریخچه حذف شد."}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.BASE_DIR / "templates" / "index.html")
