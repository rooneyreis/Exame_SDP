# Build context: repository root (so the shared "common" package can be copied).
FROM python:3.12-slim

WORKDIR /app
COPY services/coordinator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/coordinator/coordinator_service /app/coordinator_service

ENV PYTHONUNBUFFERED=1
EXPOSE 8020

CMD ["uvicorn", "coordinator_service.main:app", "--host", "0.0.0.0", "--port", "8020", \
     "--ssl-keyfile", "/certs/coordinator.key", "--ssl-certfile", "/certs/coordinator.crt", "--no-access-log"]
