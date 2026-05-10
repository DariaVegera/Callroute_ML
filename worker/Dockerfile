FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Структура в контейнере:
# /app/celery_app.py
# /app/tasks/
# /app/ml/
# /app/api/          <- копируем для импортов billing_service и models
COPY worker/ml/models/ /app/models/
COPY worker/ /app/
COPY api/ /app/api/

ENV PYTHONPATH=/app
