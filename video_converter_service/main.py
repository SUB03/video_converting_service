import asyncio
import datetime
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from video_converter_service.config import settings
from video_converter_service.engine import engine, get_session
from video_converter_service.models import Base, Outbox, Video, VideoFormat
from video_converter_service.relay import outbox_relay_worker
from video_converter_service.storage import detect_format, save_upload

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.video_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    relay_task = asyncio.create_task(outbox_relay_worker())
    yield
    relay_task.cancel()
    with suppress(asyncio.CancelledError):
        await relay_task
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    return {"Hello": "World"}

@app.post("/videos")
async def load_video(
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_session)],
    target_formats: Annotated[list[VideoFormat] | None, Form()] = None,
):
    source_format = detect_format(file.filename)
    target_formats = [f for f in dict.fromkeys(target_formats) if f != source_format]
    if not target_formats:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "target_formats must contain a format different from the source format",
        )

    job_id, path = await run_in_threadpool(
        save_upload, file.file, settings.video_dir, source_format.value
    )

    # Job + outbox event in one transaction; a re-upload of the same file is a no-op
    async with session.begin():
        created = (
            await session.execute(
                insert(Video)
                .values(
                    job_id=job_id,
                    path=str(path),
                    source_format=source_format,
                    target_formats=target_formats,
                    expires_at=datetime.datetime.now(datetime.UTC) + settings.video_ttl,
                )
                .on_conflict_do_nothing(index_elements=[Video.job_id])
                .returning(Video.job_id)
            )
        ).scalar_one_or_none() is not None

        if created:
            session.add(
                Outbox(
                    event_type="video.uploaded",
                    payload={
                        "job_id": job_id,
                        "path": str(path),
                        "source_format": source_format,
                        "target_formats": target_formats,
                    },
                )
            )

    video = await session.get(Video, job_id)
    return {
        "job_id": video.job_id,
        "created": created,
        "status": video.status,
        "source_format": video.source_format,
        "target_formats": video.target_formats,
        "expires_at": video.expires_at,
    }

@app.get("/videos/{job_id}/events")
async def video_events(job_id: str, request: Request):
    ...
