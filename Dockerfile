FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Базовые пакеты: curl (для отладки) и сертификаты
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ---- Установка зависимостей ----
# Вариант 1: Poetry (если есть backend/pyproject.toml)
COPY backend/pyproject.toml backend/poetry.lock* /app/backend/

RUN pip install --no-cache-dir poetry \
 && cd /app/backend \
 && poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi --only main

# ---- Код приложения ----
COPY backend /app/backend

EXPOSE 8000

# Запуск FastAPI
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
