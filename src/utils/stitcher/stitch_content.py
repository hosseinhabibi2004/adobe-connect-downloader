import re
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from src.utils.stitcher.content_type import ContentType


if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from src.utils.stitcher.audio_video_content import AudioVideoContent


def parse_ffmpeg_time(t: str) -> float:
    h, m, s = t.split(":")
    return float(h) * 3600 + float(m) * 60 + float(s)


def run_ffmpeg_with_progress(
    cmd: list[str],
    duration: float,
    callback: callable[[str, float, str], None],
    stage: str,
    message: str,
) -> None:

    process = subprocess.Popen(  # noqa: S603
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
        universal_newlines=True,
    )

    time_pattern = re.compile(r"time=(\d+:\d+:\d+\.\d+)")

    for line in process.stderr:
        match = time_pattern.search(line)

        if match and callback:
            current = parse_ffmpeg_time(match.group(1))
            progress = min(current / duration, 1.0)
            callback(stage, progress, message)

    process.wait()


def find_start_of_all_content(content: list[AudioVideoContent]) -> datetime:
    return min(content, key=lambda e: e.start_date).start_date


def set_offsets_from_start(
    all_content: list[AudioVideoContent], global_start: datetime
) -> None:
    for content in all_content:
        content.offset_from_start = content.start_date - global_start


def generate_empty_video(
    duration: timedelta,
    connect_dir: Path,
    callback: callable[[str, float, str], None] | None = None,
) -> Path:

    file_name = Path(str((connect_dir / f"empty_{duration}.mkv").absolute()))

    if not file_name.exists():
        if callback:
            callback("ffmpeg_blank", 0.0, "Generating blank video segment")

        cmd = [
            "ffmpeg",
            "-t",
            str(duration.total_seconds()),
            "-s",
            "1280x720",
            "-f",
            "rawvideo",
            "-r",
            "1",
            "-i",
            "/dev/zero",
            str(file_name.absolute()),
        ]

        run_ffmpeg_with_progress(
            cmd,
            duration.total_seconds(),
            callback,
            "ffmpeg_blank",
            "Generating blank video",
        )

        if callback:
            callback("ffmpeg_blank", 1.0, "Blank video ready")

    return file_name


def convert_to_mkv(
    flv_video: AudioVideoContent,
    callback: callable[[str, float, str], None] | None = None,
) -> AudioVideoContent:

    out_file = Path(f"{flv_video.path_str}.mkv")

    if not out_file.exists():
        duration = flv_video.duration.total_seconds()

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            flv_video.path_str,
            "-vf",
            "fps=30",
            "-vsync",
            "cfr",
            "-s",
            "1280x720",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            str(out_file),
        ]

        run_ffmpeg_with_progress(
            cmd,
            duration,
            callback,
            "ffmpeg_convert",
            f"Converting {flv_video.path.name}",
        )

    flv_video.path = out_file

    return flv_video


def concat_videos(
    videos: list[Path],
    connect_dir: Path,
    callback: callable[[str, float, str], None] | None = None,
) -> Path:

    temp = NamedTemporaryFile("w")  # noqa: SIM115

    temp.writelines([f"file '{p!s}'\n" for p in videos])

    temp.flush()

    concat_output = connect_dir / "all_videos.mkv"

    if not concat_output.exists():
        if callback:
            callback("ffmpeg_concat", 0.0, "Concatenating video segments")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            temp.name,
            "-c",
            "copy",
            str(concat_output.absolute()),
        ]

        subprocess.run(cmd)  # noqa: PLW1510, S603

        if callback:
            callback("ffmpeg_concat", 1.0, "Video concatenation complete")

    return concat_output


def stitch(
    content: list[AudioVideoContent],
    connect_dir: Path,
    callback: callable[[str, float, str], None] | None = None,
) -> Path:

    global_start = find_start_of_all_content(content)

    set_offsets_from_start(content, global_start)

    audio_content = sorted(
        [elm for elm in content if elm.content_type is ContentType.AUDIO],
        key=lambda e: e.start_date,
    )

    video_content = sorted(
        [
            convert_to_mkv(elm, callback)
            for elm in content
            if elm.content_type is ContentType.VIDEO
        ],
        key=lambda e: e.start_date,
    )

    audio_filter_parts = []
    audio_output_streams = []
    for i, content_elm in enumerate(audio_content):
        delay = round(content_elm.offset_from_start.total_seconds())
        audio_filter_parts.append(f"[{i}]adelay={delay}s|{delay}s[s{i}];")
        audio_output_streams.append(f"[s{i}]")
    audio_filter_parts.append(
        f"{''.join(audio_output_streams)}amix=inputs={len(audio_filter_parts)}[mixout]"
    )

    videos_paths_with_blanks = []
    if video_content[0].start_date != global_start:
        videos_paths_with_blanks.append(
            str(
                generate_empty_video(
                    video_content[0].offset_from_start, connect_dir
                ).absolute()
            )
        )
    videos_paths_with_blanks.append(video_content[0].path_str)

    if len(video_content) >= 2:  # noqa: PLR2004
        for i in range(1, len(video_content)):
            previous_video = video_content[i - 1]
            video_delta = video_content[i].start_date - (
                previous_video.start_date + previous_video.duration
            )
            videos_paths_with_blanks.append(
                str(generate_empty_video(video_delta, connect_dir).absolute())
            )
            videos_paths_with_blanks.append(video_content[i].path_str)

    all_videos = concat_videos(videos_paths_with_blanks, connect_dir)

    input_command = []
    for elm in audio_content:
        input_command.append("-i")
        input_command.append(elm.path_str)
    input_command.extend(["-i", str(all_videos.absolute())])

    final_output = connect_dir / "final_output.mkv"
    cmd = [
        "ffmpeg",
        *input_command,
        "-filter_complex",
        "".join(audio_filter_parts),
        "-map",
        "[mixout]:a",
        "-map",
        f"{len(audio_output_streams)}:v",
        "-c:v",
        "copy",
        str(final_output.absolute()),
    ]

    if callback:
        callback("ffmpeg_mux", 0.0, "Muxing final video")

    subprocess.run(cmd)  # noqa: PLW1510, S603

    if callback:
        callback("ffmpeg_mux", 1.0, "Muxing complete")

    return final_output
