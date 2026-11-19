# Build context: repository root (so the shared "common" package can be copied).
FROM python:3.12-slim

WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/api/api_service /app/api_service

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Each instance uses its own certificate (api-1.crt / api-2.crt), chosen by INSTANCE_ID.
CMD exec uvicorn api_service.main:app --host 0.0.0.0 --port 8000 \
      --ssl-keyfile /certs/${INSTANCE_ID}.key --ssl-certfile /certs/${INSTANCE_ID}.crt \
      --proxy-headers --forwarded-allow-ips 172.28.0.10 --no-access-log
