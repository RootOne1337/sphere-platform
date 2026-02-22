FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/

# Переменные должны передаваться через .env или docker run -e
ENV SPHERE_SERVER_URL=""
ENV SPHERE_AGENT_TOKEN=""
ENV SPHERE_WORKSTATION_ID=""

CMD ["python", "-m", "agent.main"]
