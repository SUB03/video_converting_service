import hashlib
import io

import pytest
from fastapi import HTTPException

from video_converter_service.models import VideoFormat
from video_converter_service.storage import detect_format, save_upload


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("clip.mov", VideoFormat.MOV), ("CLIP.MP4", VideoFormat.MP4), ("a.b.webm", VideoFormat.WEBM)],
)
def test_detect_format(filename, expected):
    assert detect_format(filename) == expected


@pytest.mark.parametrize("filename", ["notes.txt", "noext", "", None])
def test_detect_format_rejects_unsupported(filename):
    with pytest.raises(HTTPException) as exc:
        detect_format(filename)
    assert exc.value.status_code == 415


def test_save_upload_hashes_and_stores_content(tmp_path):
    content = b"some video bytes" * 100_000  # > 1 chunk
    job_id, path = save_upload(io.BytesIO(content), tmp_path, "mov")

    assert job_id == hashlib.sha256(content).hexdigest()
    assert path == tmp_path / f"{job_id}.mov"
    assert path.read_bytes() == content
    assert not list(tmp_path.glob("tmp-*"))


def test_save_upload_same_content_same_path(tmp_path):
    first = save_upload(io.BytesIO(b"same"), tmp_path, "mp4")
    second = save_upload(io.BytesIO(b"same"), tmp_path, "mp4")

    assert first == second
    assert len(list(tmp_path.iterdir())) == 1
