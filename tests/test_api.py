import asyncio
import hashlib
import json

from sqlalchemy import text

from tests.conftest import job_row, outbox_count, sync_engine, wait_until
from video_converter_service.models import VideoFormat
from video_converter_service.storage import converted_path

CONTENT = b"fake video content"
JOB_ID = hashlib.sha256(CONTENT).hexdigest()


async def upload(client, formats, filename="clip.mov", content=CONTENT):
    return await client.post(
        "/videos",
        files={"file": (filename, content)},
        data={"target_formats": formats},
    )


# --- upload ---------------------------------------------------------------

async def test_upload_creates_job_and_outbox_event(client):
    resp = await upload(client, ["mp4", "webm"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == JOB_ID
    assert body["created"] is True
    assert body["added_formats"] == ["mp4", "webm"]
    assert body["source_format"] == "mov"
    assert body["status"] == "pending"
    assert outbox_count() == 1


async def test_reupload_same_formats_is_noop(client):
    await upload(client, ["mp4"])
    resp = await upload(client, ["mp4"])

    body = resp.json()
    assert body["created"] is False
    assert body["added_formats"] == []
    assert outbox_count() == 1


async def test_reupload_adds_new_formats_and_requeues_done_job(client):
    await upload(client, ["mp4"])
    with sync_engine.begin() as conn:
        conn.execute(text("UPDATE video_table SET status = 'done'"))

    resp = await upload(client, ["mp4", "gif"])

    body = resp.json()
    assert body["created"] is False
    assert body["added_formats"] == ["gif"]
    assert body["target_formats"] == ["mp4", "gif"]
    assert body["status"] == "pending"
    assert outbox_count() == 2


async def test_upload_drops_duplicates_and_source_format(client):
    resp = await upload(client, ["mp4", "mov", "mp4"])
    assert resp.json()["target_formats"] == ["mp4"]


async def test_upload_unknown_extension_is_415(client):
    resp = await upload(client, ["mp4"], filename="notes.txt")
    assert resp.status_code == 415


async def test_upload_without_target_formats_is_422(client):
    resp = await client.post("/videos", files={"file": ("clip.mov", CONTENT)})
    assert resp.status_code == 422


async def test_upload_only_source_format_is_422(client):
    resp = await upload(client, ["mov"])
    assert resp.status_code == 422


# --- download -------------------------------------------------------------

def _write_output(job_id: str, fmt: VideoFormat, data: bytes = b"converted") -> None:
    path = converted_path(job_id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def test_download_existing_output(client, insert_job):
    job_id = insert_job(status="done", target_formats=[VideoFormat.MP4])
    _write_output(job_id, VideoFormat.MP4)

    resp = await client.get(f"/videos/{job_id}/files/mp4")

    assert resp.status_code == 200
    assert resp.content == b"converted"
    assert resp.headers["content-disposition"] == f'attachment; filename="{job_id[:12]}.mp4"'


async def test_download_works_while_other_formats_convert(client, insert_job):
    job_id = insert_job(status="processing", target_formats=[VideoFormat.MP4, VideoFormat.GIF])
    _write_output(job_id, VideoFormat.MP4)

    assert (await client.get(f"/videos/{job_id}/files/mp4")).status_code == 200
    assert (await client.get(f"/videos/{job_id}/files/gif")).status_code == 404  # not converted yet


async def test_download_not_requested_format_is_404(client, insert_job):
    job_id = insert_job(status="done", target_formats=[VideoFormat.MP4])
    _write_output(job_id, VideoFormat.AVI)  # exists on disk, but wasn't requested

    assert (await client.get(f"/videos/{job_id}/files/avi")).status_code == 404


async def test_download_unknown_job_is_404(client):
    assert (await client.get("/videos/nope/files/mp4")).status_code == 404


async def test_download_invalid_format_is_422(client, insert_job):
    job_id = insert_job()
    assert (await client.get(f"/videos/{job_id}/files/exe")).status_code == 422


# --- SSE ------------------------------------------------------------------

def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_events_for_done_job(client, insert_job):
    job_id = insert_job(status="done", target_formats=[VideoFormat.MP4])

    resp = await client.get(f"/videos/{job_id}/events")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert parse_sse(resp.text) == [
        ("done", {"files": [{"format": "mp4", "url": f"/videos/{job_id}/files/mp4"}]}),
    ]


async def test_events_stream_status_changes_until_done(client, insert_job, job_events):
    job_id = insert_job(status="pending", target_formats=[VideoFormat.MP4])

    request = asyncio.create_task(client.get(f"/videos/{job_id}/events"))
    await wait_until(lambda: job_id in job_events._subscribers)

    for status in ("processing", "done"):
        with sync_engine.begin() as conn:
            conn.execute(text("UPDATE video_table SET status = :s"), {"s": status})

    resp = await asyncio.wait_for(request, timeout=10)
    assert [event for event, _ in parse_sse(resp.text)] == ["status", "status", "done"]
    assert [data.get("status") for _, data in parse_sse(resp.text)[:2]] == ["pending", "processing"]


async def test_events_failed_job(client, insert_job):
    job_id = insert_job(status="failed")
    resp = await client.get(f"/videos/{job_id}/events")
    assert parse_sse(resp.text) == [("error", {"message": "Conversion failed"})]


async def test_events_unknown_job_is_404(client):
    assert (await client.get("/videos/nope/events")).status_code == 404


def test_job_row_helper_sanity(insert_job):
    job_id = insert_job(target_formats=[VideoFormat.GIF])
    assert job_row(job_id).target_formats == ["gif"]
