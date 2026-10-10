ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости (отдельный слой для кэша)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Stamp source only after dependency layers so each commit can reuse them.
ARG BUILD_SHA=unknown
ENV SPHERE_BUILD_SHA=${BUILD_SHA}

# Исходный код (контекст = корень проекта, см. .dockerignore)
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY agent-config/ ./agent-config/
# Bootstrap is executed inside this image by full-deploy (no dev source mount).
COPY scripts/create_admin.py scripts/seed_enrollment_key.py ./scripts/
# Reviewed, tenant-explicit maintenance is packaged; no host source mounts.
COPY scripts/backfill_script_metadata.py scripts/publish_script_source.py ./scripts/

# Запуск от non-root пользователя
RUN useradd -r -u 1001 sphere \
    && mkdir -p /app/backend/updates /tmp/sphere-metrics /var/lib/sphere/device-logs \
    && chown sphere:sphere /app/backend/updates /tmp/sphere-metrics /var/lib/sphere/device-logs
USER sphere

ENV PYTHONPATH=/app

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "/app/backend/docker-entrypoint.sh"]

# Production: gunicorn + uvicorn workers, graceful restart при утечке памяти
CMD ["gunicorn", "backend.main:app", \
     "--config", "backend/gunicorn_conf.py", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--graceful-timeout", "30", \
     "--timeout", "120", \
     "--keep-alive", "65", \
     "--max-requests", "10000", \
     "--max-requests-jitter", "1000", \
     "--access-logfile", "-"]
