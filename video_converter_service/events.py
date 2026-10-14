import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from sqlalchemy import make_url

from video_converter_service.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "video_events"
TERMINAL_STATUSES = {"done", "failed"}

# Any status change on video_table (by the worker or anyone else) becomes a NOTIFY
TRIGGER_DDL = [
    f"""
    CREATE OR REPLACE FUNCTION notify_video_event() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify('{CHANNEL}', json_build_object(
            'job_id', NEW.job_id,
            'status', NEW.status,
            'target_formats', NEW.target_formats
        )::text);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE TRIGGER video_events
    AFTER UPDATE OF status ON video_table
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION notify_video_event()
    """,
]


def to_sse(job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Job state {job_id, status, target_formats} -> (SSE event name, data)."""
    if job["status"] == "done":
        files = [
            {"format": fmt, "url": f"/videos/{job['job_id']}/files/{fmt}"}
            for fmt in job["target_formats"]
        ]
        return "done", {"files": files}
    if job["status"] == "failed":
        return "error", {"message": "Conversion failed"}
    return "status", {"status": job["status"]}


class JobEvents:
    """One LISTEN connection per process, fanned out to per-job subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncGenerator[asyncio.Queue[dict[str, Any]], None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[job_id].add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(job_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscribers[job_id]

    def _dispatch(self, payload: str) -> None:
        event = json.loads(payload)
        for queue in self._subscribers.get(event["job_id"], ()):
            queue.put_nowait(event)

    async def run(self) -> None:
        # psycopg wants a plain postgresql:// URL, not SQLAlchemy's postgresql+psycopg://
        conninfo = (
            make_url(str(settings.database_url))
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    logger.info("listening for %s notifications", CHANNEL)
                    async for notify in conn.notifies():
                        self._dispatch(notify.payload)
            except asyncio.CancelledError:
                logger.info("job events listener stopped")
                raise
            except Exception:
                logger.exception("job events listener failed, reconnecting")
                await asyncio.sleep(1)


job_events = JobEvents()
