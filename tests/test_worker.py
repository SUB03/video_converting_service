import threading
import time

import pytest
from sqlalchemy import text

from tests.conftest import VIDEO_DIR, job_row, probe_codecs, requires_ffmpeg, sync_engine
from video_converter_service.models import VideoFormat
from video_converter_service.storage import converted_path
from video_converter_service.worker import _claim, _finish, convert_video

# --- _claim ---------------------------------------------------------------

@pytest.mark.parametrize("status", ["pending", "failed"])
def test_claim_claimable_job(insert_job, status):
    job_id = insert_job(status=status)
    assert _claim(job_id, redelivered=False) is True
    assert job_row(job_id).status == "processing"


def test_claim_done_job_is_refused(insert_job):
    job_id = insert_job(status="done")
    assert _claim(job_id, redelivered=False) is False
    assert job_row(job_id).status == "done"


def test_claim_processing_job_only_when_redelivered(insert_job):
    job_id = insert_job(status="processing")
    assert _claim(job_id, redelivered=False) is False  # another worker has it
    assert _claim(job_id, redelivered=True) is True    # previous worker died


# --- _finish (compare-and-set) --------------------------------------------

def test_finish_sets_done_when_formats_unchanged(insert_job):
    job_id = insert_job(status="processing", target_formats=[VideoFormat.MP4])
    assert _finish(job_id, [VideoFormat.MP4]) is True
    assert job_row(job_id).status == "done"


def test_finish_refuses_when_formats_were_added(insert_job):
    job_id = insert_job(status="processing", target_formats=[VideoFormat.MP4, VideoFormat.GIF])
    assert _finish(job_id, [VideoFormat.MP4]) is False
    assert job_row(job_id).status == "processing"


def test_finish_waits_for_concurrent_reupload_and_sees_new_formats(insert_job):
    """The race: a re-upload holds the row lock and appends a format while the worker finishes."""
    job_id = insert_job(status="processing", target_formats=[VideoFormat.MP4])
    result: dict[str, bool] = {}

    with sync_engine.connect() as uploader:
        tx = uploader.begin()
        uploader.execute(text("SELECT 1 FROM video_table WHERE job_id = :id FOR UPDATE"), {"id": job_id})
        uploader.execute(
            text("UPDATE video_table SET target_formats = array_append(target_formats, 'gif') "
                 "WHERE job_id = :id"),
            {"id": job_id},
        )

        worker = threading.Thread(target=lambda: result.update(done=_finish(job_id, [VideoFormat.MP4])))
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive(), "_finish should block on the uploader's row lock"

        tx.commit()
        worker.join(timeout=5)

    assert result == {"done": False}
    assert job_row(job_id).status == "processing"


# --- convert_video (real ffmpeg) ------------------------------------------

def _run_task(job_id: str, path, source="mov", targets=("mp4",)):
    return convert_video.apply(
        kwargs={"job_id": job_id, "path": str(path), "source_format": source,
                "target_formats": list(targets)},
        task_id=job_id,
    )


@requires_ffmpeg
def test_convert_video_produces_outputs(insert_job, make_clip):
    clip = make_clip("mov")
    job_id = insert_job(target_formats=[VideoFormat.MP4, VideoFormat.WEBM], path=str(clip))

    result = _run_task(job_id, clip, targets=("mp4", "webm"))

    assert result.successful(), result.traceback
    assert job_row(job_id).status == "done"
    assert probe_codecs(converted_path(job_id, VideoFormat.MP4)) == ["h264", "aac"]
    assert probe_codecs(converted_path(job_id, VideoFormat.WEBM)) == ["vp9", "opus"]
    assert not list((converted_path(job_id, VideoFormat.MP4).parent).glob("tmp-*"))


@requires_ffmpeg
def test_convert_video_skips_existing_output(insert_job, make_clip):
    clip = make_clip("mov")
    job_id = insert_job(target_formats=[VideoFormat.MP4], path=str(clip))
    existing = converted_path(job_id, VideoFormat.MP4)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"already converted")

    assert _run_task(job_id, clip).successful()

    assert existing.read_bytes() == b"already converted"
    assert job_row(job_id).status == "done"


@requires_ffmpeg
def test_convert_video_corrupt_input_fails(insert_job, tmp_path):
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"\x00not a video" * 1000)
    job_id = insert_job(path=str(broken))

    result = _run_task(job_id, broken)

    assert result.failed()
    assert "ffmpeg failed for mp4" in str(result.result)
    assert job_row(job_id).status == "failed"


def test_convert_video_skips_done_job(insert_job):
    job_id = insert_job(status="done", path=f"{VIDEO_DIR}/does-not-exist.mov")
    assert _run_task(job_id, "/does-not-exist.mov").successful()  # nothing to do, no ffmpeg call
    assert job_row(job_id).status == "done"
