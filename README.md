# test_payment_system

A learning project. It currently contains a FastAPI video converter service backed by PostgreSQL and RabbitMQ, and a TanStack Start frontend for uploading videos and watching conversion progress.

## Services

| Service           | Port         | Description                                        |
|-------------------|--------------|----------------------------------------------------|
| `frontend`        | 3000         | TanStack Start app; proxies `/api/*` to `video_converter` |
| `video_converter` | 8000         | FastAPI app that accepts video uploads (ffmpeg included in the image); runs the outbox relay in the background |
| `celery_worker`   | –            | Celery worker consuming `convert_video` tasks from the `video.convert` queue (placeholder: only logs) |
| `postgres`        | 5432         | PostgreSQL 17, for job state and the outbox table  |
| `rabbitmq`        | 5672, 15672  | RabbitMQ 4 message broker for conversion jobs; management UI on 15672 |

## Project layout

```
.
├── docker-compose.yaml
├── requirements.txt
├── frontend/                 # TanStack Start (React) app
│   ├── Dockerfile
│   ├── vite.config.ts        # /api proxy to the backend
│   └── src/
│       ├── routes/index.tsx  # upload page
│       ├── hooks/useJobEvents.ts
│       └── lib/api.ts
└── video_converter_service/
    ├── Dockerfile
    ├── config.py
    ├── engine.py
    └── main.py
```

## Running with Docker

```bash
docker compose up --build
```

Then open:

- Frontend: http://localhost:3000
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

# Frontend, in another terminal (proxies /api to http://localhost:8000)
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

Video conversion needs `ffmpeg` installed on your machine.

## Configuration

| Variable       | Default (in compose)                 | Description           |
|----------------|--------------------------------------|-----------------------|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@postgres:5432/video_converter` | PostgreSQL connection URL. Use `localhost` instead of `postgres` as the host when running the app outside Docker. |
| `RABBITMQ_URL` | `amqp://guest:guest@rabbitmq:5672/`  | RabbitMQ connection URL. Use `amqp://guest:guest@localhost:5672/` when running the app outside Docker. |
| `API_URL` (frontend) | `http://video_converter:8000`  | Backend the frontend proxies `/api/*` to. Read at build time (a Docker build arg); defaults to `http://localhost:8000` for `npm run dev`. |

## API

| Method | Path      | Description            |
|--------|-----------|------------------------|
| GET    | `/`       | Health / hello world   |
| POST   | `/videos` | Upload a video (WIP)   |
