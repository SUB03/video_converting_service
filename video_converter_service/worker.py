import os
import uuid
from pathlib import Path
from typing import Any

import ffmpeg
from celery import Celery
from celery.signals import worker_process_init
from celery.utils.log import get_task_logger
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from video_converter_service.config import settings
from video_converter_service.models import Video, VideoFormat
from video_converter_service.storage import CONVERTED_DIR, converted_path

celery_app = Celery("video_converter", broker=str(settings.rabbitmq_url))
celery_app.conf.update(
    task_default_queue=settings.convert_queue,
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"confirm_publish": True},
    broker_connection_retry_on_startup=True,
    worker_enable_remote_control=False,
)

logger = get_task_logger(__name__)

# Celery tasks are sync, so they get a sync engine (psycopg 3 does both)
engine = create_engine(str(settings.database_url), pool_pre_ping=True)


@worker_process_init.connect
def _reset_db_pool(**_):
    # Each forked pool process must open its own connections, not reuse the parent's
    engine.dispose(close=False)


# ffmpeg output options per target format; None means a flag without a value (-an)
_H264: dict[str, Any] = {
    "vf": "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # libx264 + yuv420p needs even width/height
    "vcodec": "libx264", "preset": "veryfast", "crf": 23, "pix_fmt": "yuv420p",
    "acodec": "aac",
}
FFMPEG_OPTIONS: dict[VideoFormat, dict[str, Any]] = {
    VideoFormat.MP4: {**_H264, "movflags": "+faststart"},
    VideoFormat.MOV: _H264,
    VideoFormat.MKV: _H264,
    VideoFormat.WEBM: {
        "vcodec": "libvpx-vp9", "b:v": 0, "crf": 35, "deadline": "realtime",
        "cpu-used": 8, "row-mt": 1, "acodec": "libopus",
    },
    VideoFormat.AVI: {"vcodec": "mpeg4", "q:v": 5, "acodec": "libmp3lame"},
    VideoFormat.GIF: {
        "vf": "fps=10,scale=480:-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
        "an": None,
    },
}


def _claim(job_id: str, redelivered: bool) -> bool:
    """Atomically move the job to 'processing'. False = done already or another worker has it."""
    claimable = ["pending", "failed"]
    if redelivered:
        # RabbitMQ only redelivers if the worker that had it died before acking,
        # so a job stuck in 'processing' is ours to take over
        claimable.append("processing")
    with Session(engine) as session, session.begin():
        claimed = session.execute(
            update(Video)
            .where(Video.job_id == job_id, Video.status.in_(claimable))
            .values(status="processing")
            .returning(Video.job_id)
        ).scalar_one_or_none()
    return claimed is not None


def _set_status(job_id: str, status: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(update(Video).where(Video.job_id == job_id).values(status=status))


def _job_state(job_id: str) -> tuple[str, list[VideoFormat]]:
    """Current (status, target_formats). The DB, not the task payload, is the source of truth."""
    with Session(engine) as session:
        status, formats = session.execute(
            select(Video.status, Video.target_formats).where(Video.job_id == job_id)
        ).one()
    return status, list(formats)


def _finish(job_id: str, formats: list[VideoFormat]) -> bool:
    """
    Set 'done' only if no formats were added since we read `formats`.

    Formats are only ever appended, so a changed length means a re-upload added some.
    If that re-upload is still in flight, this UPDATE waits on its row lock and then
    re-checks the WHERE against the committed row.
    """
    with Session(engine) as session, session.begin():
        done = session.execute(
            update(Video)
            .where(
                Video.job_id == job_id,
                Video.status == "processing",
                func.cardinality(Video.target_formats) == len(formats),
            )
            .values(status="done")
            .returning(Video.job_id)
        ).scalar_one_or_none()
    return done is not None


def _convert(src: Path, out: Path, fmt: VideoFormat) -> None:
    # Write to a temp file and rename, so `out` existing always means a complete file
    tmp = out.with_name(f"tmp-{uuid.uuid4()}{out.suffix}")
    try:
        (
            ffmpeg.input(str(src))
            .output(str(tmp), **FFMPEG_OPTIONS[fmt])
            .global_args("-nostdin", "-hide_banner", "-loglevel", "error")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        os.replace(tmp, out)
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace").strip()[-500:]
        raise RuntimeError(f"ffmpeg failed for {fmt}: {stderr}") from None
    finally:
        tmp.unlink(missing_ok=True)


@celery_app.task(name="convert_video", bind=True)
def convert_video(self, job_id: str, path: str, source_format: str, target_formats: list[str]):
    # job_id is the task id, so a redelivery or re-sent outbox row repeats it
    redelivered = bool((self.request.delivery_info or {}).get("redelivered"))
    if not _claim(job_id, redelivered):
        logger.info("skipping %s: already done or being processed", job_id)
        return

    try:
        CONVERTED_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            # Re-read every round: a re-upload may add formats while we convert
            status, formats = _job_state(job_id)
            if status != "processing":
                logger.warning("stopping %s: status changed to %r", job_id, status)
                return
            for fmt in formats:
                out = converted_path(job_id, fmt)
                if out.exists():  # converted earlier (previous attempt or upload)
                    logger.info("%s -> %s already exists, skipping", job_id, fmt)
                    continue
                logger.info("converting %s: %s -> %s", job_id, source_format, fmt)
                _convert(Path(path), out, fmt)
            if _finish(job_id, formats):
                break
            logger.info("%s: formats were added during conversion, continuing", job_id)
    except Exception:
        _set_status(job_id, "failed")
        raise

    logger.info("done %s: %s", job_id, ", ".join(formats))
