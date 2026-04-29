from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from pathlib import Path

    from src.utils.stitcher.content_type import ContentType


@dataclass
class AudioVideoContent:
    path: Path
    content_type: ContentType
    start_date: datetime
    duration: timedelta
    offset_from_start: timedelta | None = None

    @property
    def path_str(self) -> str:
        return str(self.path.absolute())
