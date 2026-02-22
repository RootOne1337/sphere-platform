FROM python:3.12-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости (отдельный слой для кэша)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY . .

# Запуск от non-root пользователя
RUN useradd -r -u 1001 sphere
USER sphere

EXPOSE 8000

# Production: без --reload, с worker limits для graceful restart
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100"]
