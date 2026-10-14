import os
import shutil
import subprocess
import tempfile

# Settings, engines and CONVERTED_DIR are created at import time, so configure the
# environment before importing anything from the app.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/video_converter_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["RABBITMQ_URL"] = "amqp://guest:guest@localhost:5672/"  # never connected: send_task is mocked
VIDEO_DIR = tempfile.mkdtemp(prefix="video_converter_tests-")
os.environ["VIDEO_DIR"] = VIDEO_DIR

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine, make_url, select, text  # noqa: E402

from video_converter_service import main  # noqa: E402
from video_converter_service.engine import engine as async_engine  # noqa: E402
from video_converter_service.events import TRIGGER_DDL, JobEvents  # noqa: E402
from video_converter_service.models import Base, Video, VideoFormat  # noqa: E402
from video_converter_service.worker import celery_app  # noqa: E402

_url = make_url(TEST_DATABASE_URL)
if not _url.database or not _url.database.endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against non-test database {_url.database!r}")

sync_engine = create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def database():
    """Create the test database if needed and rebuild the schema from the models."""
    admin = create_engine(_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_url.database}"'))
    admin.dispose()

    with sync_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        for ddl in TRIGGER_DDL:
            conn.exec_driver_sql(ddl)
    yield
    sync_engine.dispose()
    shutil.rmtree(VIDEO_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
async def clean_state():
    with sync_engine.begin() as conn:
        conn.execute(text("TRUNCATE video_table, outbox RESTART IDENTITY"))
    for entry in Path(VIDEO_DIR).iterdir():
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    yield
    # The async engine is a module global; drop its pooled connections so the next
    # test (which runs in a fresh event loop) doesn't reuse ones from this loop
    await async_engine.dispose()


async def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


def _listener_connected() -> bool:
    with sync_engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT 1 FROM pg_stat_activity "
            "WHERE datname = current_database() AND query = 'LISTEN video_events'"
        )).scalar())


@pytest.fixture
async def job_events(monkeypatch):
    """A fresh JobEvents listener, connected and LISTENing, wired into the app."""
    events = JobEvents()
    monkeypatch.setattr(main, "job_events", events)
    task = asyncio.create_task(events.run())
    await wait_until(_listener_connected)
    yield events
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.fixture
async def client(job_events):
    # No lifespan: the outbox relay never starts, so nothing talks to RabbitMQ
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


@pytest.fixture
def sent_tasks(monkeypatch):
    """Replace Celery's send_task; records each call's (name, kwargs-dict)."""
    calls: list[tuple[str, dict]] = []

    def fake_send_task(name, **kwargs):
        calls.append((name, kwargs))

    monkeypatch.setattr(celery_app, "send_task", fake_send_task)
    return calls


@pytest.fixture
def insert_job():
    def _insert(
        job_id: str = "a" * 64,
        status: str = "pending",
        source_format: VideoFormat = VideoFormat.MOV,
        target_formats: list[VideoFormat] | None = None,
        path: str | None = None,
    ) -> str:
        with sync_engine.begin() as conn:
            conn.execute(
                Video.__table__.insert().values(
                    job_id=job_id,
                    status=status,
                    source_format=source_format,
                    target_formats=target_formats or [VideoFormat.MP4],
                    path=path or f"{VIDEO_DIR}/{job_id}.{source_format}",
                    expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1),
                )
            )
        return job_id

    return _insert


def job_row(job_id: str):
    # Through the model, so the video_format[] enum array is decoded into a list
    with sync_engine.connect() as conn:
        return conn.execute(
            select(Video.status, Video.target_formats).where(Video.job_id == job_id)
        ).one_or_none()


def outbox_count() -> int:
    with sync_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM outbox")).scalar_one()


requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def make_clip(tmp_path):
    """Generate a tiny real video (1 s, 160x120, with audio) in the given container."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")

    def _make(fmt: str = "mov", name: str = "clip") -> Path:
        out = tmp_path / f"{name}.{fmt}"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
             "-f", "lavfi", "-i", "sine=duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
            check=True,
        )
        return out

    return _make


def probe_codecs(path: Path) -> list[str]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.split()
