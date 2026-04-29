import shutil
import zipfile
from typing import TYPE_CHECKING

from src.config import OUTPUT_DIR, TEMP_DIR
from src.utils.stitcher.extract_content_info import get_all_content
from src.utils.stitcher.stitch_content import stitch


if TYPE_CHECKING:
    from pathlib import Path


def convert_meeting(
    meeting_id: str, callback: callable[[str, float, str], None] | None = None
) -> Path:
    zip_path = TEMP_DIR / f"{meeting_id}.zip"
    meeting_dir = TEMP_DIR / meeting_id

    if callback:
        callback("extract", 0.0, "Extracting meeting archive")

    if not meeting_dir.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(meeting_dir)

    if callback:
        callback("extract", 1.0, "Extraction complete")

    if callback:
        callback("parse", 0.0, "Parsing meeting media")

    all_content = get_all_content(meeting_dir)

    if callback:
        callback("parse", 1.0, "Media parsing complete")

    final_video = stitch(all_content, meeting_dir, callback)

    if callback:
        callback("finalize", 0.0, "Finalizing output")

    final_path = OUTPUT_DIR / f"{meeting_id}.mkv"

    final_video.rename(final_path)

    # shutil.rmtree(meeting_dir)

    if callback:
        callback("finalize", 1.0, "Conversion complete")

    return final_path
