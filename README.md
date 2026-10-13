# test_payment_system

A learning project. It currently contains a FastAPI video converter service backed by PostgreSQL and RabbitMQ.

## Services

| Service           | Port         | Description                                        |
|-------------------|--------------|----------------------------------------------------|
| `video_converter` | 8000         | FastAPI app that accepts video uploads (ffmpeg included in the image) |
| `postgres`        | 5432         | PostgreSQL 17, for job state and the outbox table  |
| `rabbitmq`        | 5672, 15672  | RabbitMQ 4 message broker for conversion jobs; management UI on 15672 |

## Project layout

```
.
├── docker-compose.yaml
├── requirements.txt
└── video_converter_service/
    ├── Dockerfile
    └── main.py
```

## Running with Docker

```bash
docker compose up --build
```

Then open:

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- RabbitMQ management UI: http://localhost:15672 (login `guest` / `guest`)
- PostgreSQL: `psql postgresql://postgres:postgres@localhost:5432/video_converter`

Stop everything:

```bash
docker compose down        # keep volumes
docker compose down -v     # also delete Postgres/RabbitMQ data and videos
```

## Running locally (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
pip install -r requirements.txt

# Postgres and RabbitMQ only, from compose
docker compose up -d postgres rabbitmq

fastapi dev video_converter_service/main.py
```

Video conversion needs `ffmpeg` installed on your machine.

## Configuration

| Variable       | Default (in compose)                 | Description           |
|----------------|--------------------------------------|-----------------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/video_converter` | PostgreSQL connection URL. Use `localhost` instead of `postgres` as the host when running the app outside Docker. |
| `RABBITMQ_URL` | `amqp://guest:guest@rabbitmq:5672/`  | RabbitMQ connection URL. Use `amqp://guest:guest@localhost:5672/` when running the app outside Docker. |

## API

| Method | Path      | Description            |
|--------|-----------|------------------------|
| GET    | `/`       | Health / hello world   |
| POST   | `/videos` | Upload a video (WIP)   |
