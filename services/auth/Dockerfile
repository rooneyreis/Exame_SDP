# Build context: repository root (so the shared "common" package can be copied).
FROM python:3.12-slim

WORKDIR /app
COPY services/auth/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/auth/auth_service /app/auth_service

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

# HTTPS directly in Uvicorn with the certificate issued by the local CA.
CMD ["uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8010", \
     "--ssl-keyfile", "/certs/auth.key", "--ssl-certfile", "/certs/auth.crt", \
     "--proxy-headers", "--forwarded-allow-ips", "172.28.0.10", "--no-access-log"]
