FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Persisted SQLite database lives here (mount a volume to keep it).
ENV DB_PATH=/data/bot.sqlite3
VOLUME ["/data"]

CMD ["python", "-m", "bot"]
