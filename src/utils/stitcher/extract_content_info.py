from datetime import datetime, timedelta
from xml.etree import ElementTree as ET


try:
    import dateparser

    _has_dateparser = True
except ImportError:
    dateparser = None
    _has_dateparser = False

from typing import TYPE_CHECKING

import ffmpeg

from src.utils.stitcher.audio_video_content import AudioVideoContent
from src.utils.stitcher.content_type import ContentType


if TYPE_CHECKING:
    from pathlib import Path


def get_content_with_xml_info(
    content_path: Path, content_type: ContentType
) -> AudioVideoContent:
    filename = content_path.stem
    xml_info_file = content_path.parent / f"{filename}.xml"
    start_date = get_content_start_date_from_xml(xml_info_file)
    duration = timedelta(
        seconds=float(ffmpeg.probe(content_path)["format"]["duration"])
    )

    return AudioVideoContent(
        path=content_path,
        content_type=content_type,
        start_date=start_date,
        duration=duration,
    )


def get_content_start_date_from_xml(xml_path: Path) -> datetime:
    xml_info = ET.parse(xml_path)  # noqa: S314
    arrays_in_messages = [
        e.find("Array")
        for e in xml_info.getroot().findall("Message")
        if e.find("Array")
    ]

    for array in arrays_in_messages:
        for elm in array:
            try:
                return parse_date(elm.text)
            except ValueError:
                pass

    msg = f"Could not determine content start for file '{xml_path}'"
    raise RuntimeError(msg)


def parse_date(date: str) -> datetime:
    if ":" in date and len(date) >= 5:  # noqa: PLR2004
        if _has_dateparser:
            parsed = dateparser.parse(date)
            if parsed:
                return parsed
        else:
            return datetime.strptime(date, "%a %b %d %H:%M:%S %Y")  # noqa: DTZ007

    msg = "The provided string does not look like a date"
    raise ValueError(msg)


def get_all_content(connect_dir: Path) -> list[AudioVideoContent]:
    return [
        get_content_with_xml_info(audio, ContentType.AUDIO)
        for audio in connect_dir.glob("cameraVoip*.flv")
    ] + [
        get_content_with_xml_info(video, ContentType.VIDEO)
        for video in connect_dir.glob("screenshare*.flv")
    ]
