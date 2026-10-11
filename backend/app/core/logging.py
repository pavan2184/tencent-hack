"""Structured JSON logging with request/actor/job correlation fields."""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.context import actor_id_var, job_id_var, request_id_var


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.actor_id = actor_id_var.get()
        record.job_id = job_id_var.get()
        return True


_configured = False


def configure_logging(level: str = "info") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    fields = "%(asctime)s %(levelname)s %(name)s %(message)s"
    correlation = " %(request_id)s %(actor_id)s %(job_id)s"
    handler.setFormatter(JsonFormatter(fields + correlation))
    handler.addFilter(CorrelationFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "celery"):
        logging.getLogger(noisy).setLevel(max(root.level, logging.WARNING))
    _configured = True
