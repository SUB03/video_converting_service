import asyncio

from sqlalchemy import text

from tests.conftest import sync_engine
from video_converter_service.events import JobEvents, to_sse


def test_to_sse_status():
    assert to_sse({"job_id": "j", "status": "pending", "target_formats": ["mp4"]}) == (
        "status", {"status": "pending"},
    )
    assert to_sse({"job_id": "j", "status": "processing", "target_formats": ["mp4"]})[0] == "status"


def test_to_sse_done_lists_download_urls():
    event, data = to_sse({"job_id": "j", "status": "done", "target_formats": ["mp4", "gif"]})
    assert event == "done"
    assert data == {"files": [
        {"format": "mp4", "url": "/videos/j/files/mp4"},
        {"format": "gif", "url": "/videos/j/files/gif"},
    ]}


def test_to_sse_failed():
    assert to_sse({"job_id": "j", "status": "failed", "target_formats": []})[0] == "error"


async def test_dispatch_reaches_only_that_jobs_subscribers():
    events = JobEvents()
    async with events.subscribe("a") as qa1, events.subscribe("a") as qa2, events.subscribe("b") as qb:
        events._dispatch('{"job_id": "a", "status": "done"}')
        events._dispatch('{"job_id": "nobody", "status": "done"}')

        assert qa1.get_nowait()["status"] == "done"
        assert qa2.get_nowait()["status"] == "done"
        assert qb.empty()


async def test_subscribe_cleans_up_on_exit():
    events = JobEvents()
    async with events.subscribe("a"):
        assert "a" in events._subscribers
    assert events._subscribers == {}


def _set_status(job_id: str, status: str) -> None:
    with sync_engine.begin() as conn:
        conn.execute(
            text("UPDATE video_table SET status = :s WHERE job_id = :id"), {"s": status, "id": job_id}
        )


async def test_status_update_is_notified(job_events, insert_job):
    job_id = insert_job(status="pending")
    async with job_events.subscribe(job_id) as queue:
        _set_status(job_id, "processing")
        event = await asyncio.wait_for(queue.get(), timeout=5)

    assert event == {"job_id": job_id, "status": "processing", "target_formats": ["mp4"]}


async def test_update_to_same_status_is_not_notified(job_events, insert_job):
    job_id = insert_job(status="pending")
    async with job_events.subscribe(job_id) as queue:
        _set_status(job_id, "pending")  # no change: trigger's WHEN filters it out
        _set_status(job_id, "done")     # marker that the listener has caught up
        event = await asyncio.wait_for(queue.get(), timeout=5)

    assert event["status"] == "done"
    assert queue.empty()
