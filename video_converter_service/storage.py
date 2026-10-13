import hashlib
import os
import uuid
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, status

from video_converter_service.models import VideoFormat

CHUNK_SIZE = 1024 * 1024  # 1 MB


def detect_format(filename: str | None) -> VideoFormat:
    """Source format comes from the file extension: clip.MOV -> VideoFormat.MOV."""
    ext = Path(filename or "").suffix.lower().lstrip(".")
    try:
        return VideoFormat(ext)
    except ValueError:
        supported = ", ".join(f.value for f in VideoFormat)
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file extension {ext!r}. Supported: {supported}",
        ) from None


def save_upload(src: BinaryIO, video_dir: Path, ext: str) -> tuple[str, Path]:
    """
    Stream the upload to disk while hashing it. Blocking: run in a threadpool.

    Same content always ends up at the same path (<sha256>.<ext>), so retries are safe.
    """
    sha = hashlib.sha256()
    tmp = video_dir / f"tmp-{uuid.uuid4()}"
    try:
        with open(tmp, "wb") as out:
            while chunk := src.read(CHUNK_SIZE):
                sha.update(chunk)
                out.write(chunk)
        job_id = sha.hexdigest()
        path = video_dir / f"{job_id}.{ext}"
        os.replace(tmp, path)  # atomic
        return job_id, path
    finally:
        tmp.unlink(missing_ok=True)
