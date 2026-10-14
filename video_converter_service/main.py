import asyncio
import datetime
import json
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from video_converter_service.config import settings
from video_converter_service.engine import SessionLocal, engine, get_session
from video_converter_service.events import TERMINAL_STATUSES, TRIGGER_DDL, job_events, to_sse
from video_converter_service.models import Base, Outbox, Video, VideoFormat
from video_converter_service.relay import outbox_relay_worker
from video_converter_service.storage import converted_path, detect_format, save_upload

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.video_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in TRIGGER_DDL:
            await conn.exec_driver_sql(ddl)
    tasks = [
        asyncio.create_task(outbox_relay_worker()),
        asyncio.create_task(job_events.run()),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    return {"Hello": "World"}

@app.post("/videos")
async def load_video(
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_session)],
    target_formats: Annotated[list[VideoFormat], Form()],
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

    # Job + outbox event in one transaction. Re-uploading the same file adds any new
    # target formats to the existing job; otherwise it's a no-op.
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
            added_formats, all_formats = target_formats, target_formats
        else:
            # Row lock: the worker's final "done" update waits for this transaction,
            # then sees the new formats and keeps converting (see worker._finish)
            video = (
                await session.scalars(
                    select(Video).where(Video.job_id == job_id).with_for_update()
                )
            ).one()
            added_formats = [f for f in target_formats if f not in video.target_formats]
            all_formats = [*video.target_formats, *added_formats]
            if added_formats:
                video.target_formats = all_formats
                if video.status in TERMINAL_STATUSES:
                    video.status = "pending"

        if added_formats:
            session.add(
                Outbox(
                    event_type="video.uploaded",
                    payload={
                        "job_id": job_id,
                        "path": str(path),
                        "source_format": source_format,
                        "target_formats": all_formats,
                    },
                )
            )

    video = await session.get(Video, job_id)
    return {
        "job_id": video.job_id,
        "created": created,
        "added_formats": added_formats,
        "status": video.status,
        "source_format": video.source_format,
        "target_formats": video.target_formats,
        "expires_at": video.expires_at,
    }

async def _job_state(job_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        video = await session.get(Video, job_id)
    if video is None:
        return None
    return {"job_id": video.job_id, "status": video.status, "target_formats": video.target_formats}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/videos/{job_id}/events")
async def video_events(job_id: str, request: Request):
    if await _job_state(job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    async def stream():
        async with job_events.subscribe(job_id) as queue:
            # Read the current state only after subscribing, so no change can slip in between
            state, last_sent = await _job_state(job_id), None
            while True:
                if state is not None and state != last_sent:
                    yield _sse(*to_sse(state))
                    last_sent = state
                    if state["status"] in TERMINAL_STATUSES:
                        return
                try:
                    state = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keep-alive\n\n"
                    # Safety net for NOTIFYs missed while the listener was reconnecting
                    state = await _job_state(job_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/videos/{job_id}/files/{fmt}")
async def download_file(
    job_id: str,
    fmt: VideoFormat,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    video = await session.get(Video, job_id)
    path = converted_path(job_id, fmt)
    # Outputs are renamed into place only when complete, so "exists" means "ready",
    # even while other formats of the same job are still converting
    if video is None or fmt not in video.target_formats or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(path, filename=f"{job_id[:12]}.{fmt}")
