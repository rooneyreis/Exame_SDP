"""Structured JSON logs (one JSON object per line) with request_id and tx_id.

request_id / tx_id live in context variables: each asyncio task (each HTTP request)
has its own value, so concurrent requests never mix their ids.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tx_id_var: ContextVar[str | None] = ContextVar("tx_id", default=None)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self.service,
            "msg": record.getMessage(),
        }
        if (rid := request_id_var.get()) is not None:
            entry["request_id"] = rid
        if (tid := tx_id_var.get()) is not None:
            entry["tx_id"] = tid
        if extra := getattr(record, "extra_fields", None):
            entry.update(extra)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(service: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Uvicorn's own loggers go through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    return logging.getLogger(service)


def log_extra(**fields) -> dict:
    """Usage: log.info("mensagem", extra=log_extra(user_id=...))"""
    return {"extra_fields": fields}


def add_request_logging(app, logger: logging.Logger) -> None:
    """FastAPI middleware: takes X-Request-ID from nginx (or creates one), logs each
    request with method, path, status and duration, and returns X-Request-ID."""

    @app.middleware("http")
    async def request_logging(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code}",
            extra=log_extra(request_id=rid, ms=round((time.perf_counter() - start) * 1000, 1)),
        )
        response.headers["X-Request-ID"] = rid
        return response
