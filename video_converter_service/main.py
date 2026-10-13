from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from video_converter_service.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    return {"Hello": "World"}

@app.post("/videos")
async def load_video():
    return 

@app.get("/videos/{job_id}/events")
async def video_events(job_id: str, request: Request):
    ...