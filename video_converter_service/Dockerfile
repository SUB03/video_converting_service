FROM python:3.13-slim

# ffmpeg for video conversion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY video_converter_service ./video_converter_service

EXPOSE 8000

CMD ["uvicorn", "video_converter_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
