from sqlalchemy import text

from tests.conftest import outbox_count, sync_engine
from video_converter_service.relay import _relay_batch
from video_converter_service.worker import celery_app


def _add_outbox(event_type: str = "video.uploaded", job_id: str = "j1") -> None:
    with sync_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO outbox (event_type, payload) VALUES (:t, CAST(:p AS jsonb))"),
            {"t": event_type, "p": f'{{"job_id": "{job_id}", "path": "/x.mov", '
                                   f'"source_format": "mov", "target_formats": ["mp4"]}}'},
        )


async def test_relay_publishes_and_deletes(sent_tasks):
    _add_outbox(job_id="j1")
    _add_outbox(job_id="j2")

    assert await _relay_batch() == 2

    assert outbox_count() == 0
    assert [(name, kw["task_id"], kw["queue"]) for name, kw in sent_tasks] == [
        ("convert_video", "j1", "video.convert"),
        ("convert_video", "j2", "video.convert"),
    ]
    assert sent_tasks[0][1]["kwargs"]["target_formats"] == ["mp4"]
    assert sent_tasks[0][1]["retry"] is False


async def test_relay_keeps_rows_when_publish_fails(monkeypatch):
    def broken_send_task(*args, **kwargs):
        raise ConnectionError("rabbitmq down")

    monkeypatch.setattr(celery_app, "send_task", broken_send_task)
    _add_outbox()

    try:
        await _relay_batch()
    except ConnectionError:
        pass
    else:
        raise AssertionError("expected the publish error to propagate")

    assert outbox_count() == 1  # transaction rolled back, row stays for the next attempt


async def test_relay_drops_unknown_event_type(sent_tasks):
    _add_outbox(event_type="something.else")

    assert await _relay_batch() == 1

    assert sent_tasks == []
    assert outbox_count() == 0


async def test_relay_empty_outbox(sent_tasks):
    assert await _relay_batch() == 0
    assert sent_tasks == []
