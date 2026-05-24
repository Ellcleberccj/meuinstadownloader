FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl nodejs npm && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN node --version || true
RUN yt-dlp --version || true
COPY . .

CMD python patch_loading.py && gunicorn app:app --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 300
