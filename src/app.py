import threading
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from src.config import BASE_DIR, OUTPUT_DIR, TEMP_DIR
from src.utils.converter import convert_meeting


if TYPE_CHECKING:
    from pathlib import Path


app = FastAPI()

progress_store: dict[str, dict] = {}
progress_lock = Lock()


def make_progress_callback(job_id: str) -> callable[[str, float, str], None]:
    def callback(stage: str, progress: float, message: str) -> None:
        with progress_lock:
            progress_store[job_id] = {
                "stage": stage,
                "progress": progress,
                "message": message,
            }

    return callback


def build_download_link(meeting_url: str) -> tuple[str, str]:
    parsed = urlparse(meeting_url)
    query = parse_qs(parsed.query)

    if "session" not in query:
        msg = "Session not found in URL"
        raise ValueError(msg)

    session_id = query["session"][0]

    base_path = parsed.path.rstrip("/")

    meeting_id = base_path.split("/")[-1]
    download_url = (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{base_path}/output/{meeting_id}.zip"
        f"?download=zip&session={session_id}"
    )

    return download_url, meeting_id


def download_zip(
    download_url: str, meeting_id: str, callback: callable[[str, float, str], None]
) -> Path:
    path = TEMP_DIR / f"{meeting_id}.zip"

    response = requests.get(download_url, stream=True)  # noqa: S113
    total_size = int(response.headers.get("content-length", 0))

    if not path.exists():
        downloaded = 0
        with path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
                    downloaded += len(chunk)

                    progress = downloaded / total_size if total_size else 0

                    callback("download", progress, "Downloading meeting archive")

    callback("download", 1.0, "Download complete")

    return path


def process_meeting(
    download_url: str, meeting_id: str, callback: callable[[str, float, str], None]
) -> None:
    try:
        download_zip(download_url, meeting_id, callback)
        convert_meeting(meeting_id, callback)
    except Exception as e:  # noqa: BLE001
        callback("error", 1, str(e))


@app.post("/convert")
def convert(meeting_url: str) -> dict:

    download_url, meeting_id = build_download_link(meeting_url)

    callback = make_progress_callback(meeting_id)

    thread = threading.Thread(
        target=process_meeting, args=(download_url, meeting_id, callback)
    )

    thread.start()

    return {
        "status": "success",
        "download_url": f"/download/{meeting_id}",
        "progress_url": f"/progress/{meeting_id}",
    }


@app.get("/progress/{meeting_id}")
def progress(meeting_id: str) -> dict:
    with progress_lock:
        return progress_store.get(meeting_id, {})


@app.get("/download/{meeting_id}")
def download_file(meeting_id: str) -> FileResponse:
    file_path = OUTPUT_DIR / f"{meeting_id}.mkv"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="video/x-matroska",
        filename=f"{meeting_id}.mkv",
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")
