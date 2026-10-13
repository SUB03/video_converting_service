import asyncio
import logging

from sqlalchemy import delete, select

from video_converter_service.config import settings
from video_converter_service.engine import SessionLocal
from video_converter_service.models import Outbox
from video_converter_service.worker import celery_app

logger = logging.getLogger(__name__)

# outbox event_type -> Celery task name
EVENT_TASKS = {"video.uploaded": "convert_video"}


async def _relay_batch() -> int:
    """Publish one batch of outbox rows and delete them, all in one transaction."""
    async with SessionLocal() as session, session.begin():
        # 1. read db (SKIP LOCKED: other relays skip rows we hold)
        rows = (
            await session.scalars(
                select(Outbox)
                .order_by(Outbox.id)
                .limit(settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()

        # 2. send to RabbitMQ (IDEMPOTENT: task_id = job_id, so a re-send repeats the same id)
        for row in rows:
            task = EVENT_TASKS.get(row.event_type)
            if task is None:
                logger.error("dropping outbox row %s: unknown event_type %r", row.id, row.event_type)
                continue
            await asyncio.to_thread(
                celery_app.send_task,
                task,
                kwargs=row.payload,
                task_id=row.payload["job_id"],
                queue=settings.convert_queue,
                retry=False,  # fail fast; the row stays and the next loop retries
            )
            logger.info("published outbox row %s (%s) as %s", row.id, row.event_type, task)

        # 3. delete from db; if a publish above raised, we never get here and the rows stay
        if rows:
            await session.execute(delete(Outbox).where(Outbox.id.in_([r.id for r in rows])))

    return len(rows)


async def outbox_relay_worker():
    logger.info("outbox relay started")
    try:
        while True:
            try:
                sent = await _relay_batch()
            except Exception:
                logger.exception("outbox relay batch failed, retrying")
                sent = 0
            # Full batch: there may be more, go again right away
            if sent < settings.outbox_batch_size:
                await asyncio.sleep(settings.outbox_poll_interval)
    except asyncio.CancelledError:
        logger.info("outbox relay stopped")
        raise
