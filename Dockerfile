FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY scripts ./scripts

ENV POST_LIVE_WATCH_DB=/app/data/postlivewatch.db
EXPOSE 8000

# Seed only if the volume-mounted DB doesn't exist yet — a restart must never
# wipe the decision log or day-simulator state. Render injects $PORT; the
# docker-compose deploy falls back to 8000.
CMD ["sh", "-c", "test -f \"$POST_LIVE_WATCH_DB\" || python scripts/seed.py; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
