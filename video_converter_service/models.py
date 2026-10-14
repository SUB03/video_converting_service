import datetime
import enum
from typing import Any

from sqlalchemy import BigInteger
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

class Base(DeclarativeBase):
    pass

class VideoFormat(enum.StrEnum):
    MP4 = "mp4"
    WEBM = "webm"
    MKV = "mkv"
    MOV = "mov"
    AVI = "avi"
    GIF = "gif"

video_format = Enum(
    VideoFormat,
    name="video_format",
    values_callable=lambda e: [m.value for m in e],
)

class Video(Base):
    __tablename__ = "video_table"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 hex of the file
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    source_format: Mapped[VideoFormat] = mapped_column(video_format)
    target_formats: Mapped[list[VideoFormat]] = mapped_column(ARRAY(video_format))
    path: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
