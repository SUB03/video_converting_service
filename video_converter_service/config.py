import datetime
from pathlib import Path

from pydantic import AmqpDsn, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    rabbitmq_url: AmqpDsn
    db_echo: bool = False
    video_dir: Path = Path("/data/videos")
    video_ttl: datetime.timedelta = datetime.timedelta(minutes=1)  # env: VIDEO_TTL=60 or PT1M


settings = Settings()
