FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в /app чтобы импорты api.* работали
COPY api/ /app/api/
COPY migrations/ /app/migrations/
COPY alembic.ini /app/alembic.ini

ENV PYTHONPATH=/app

CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload"]
