FROM python:3.12-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости (отдельный слой для кэша)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Исходный код (контекст = корень проекта, см. .dockerignore)
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY agent-config/ ./agent-config/

# Запуск от non-root пользователя
RUN useradd -r -u 1001 sphere
USER sphere

ENV PYTHONPATH=/app

EXPOSE 8000

# Production: gunicorn + uvicorn workers, graceful restart при утечке памяти
CMD ["gunicorn", "backend.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--graceful-timeout", "30", \
     "--timeout", "120", \
     "--keep-alive", "65", \
     "--max-requests", "10000", \
     "--max-requests-jitter", "1000", \
     "--access-logfile", "-"]
