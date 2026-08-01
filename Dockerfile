FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tgparser ./tgparser
COPY pyproject.toml .

# Базу и выгрузки держим в томе, чтобы пересборка образа их не стирала.
RUN mkdir -p /app/data/exports
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/tgparser.sqlite3 \
    EXPORT_DIR=/app/data/exports

CMD ["python", "-m", "tgparser", "run"]
