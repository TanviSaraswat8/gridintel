"""Structured JSON logging, request IDs, Prometheus metrics."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter("gridintel_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("gridintel_http_request_seconds", "HTTP request latency", ["method", "route"],
                         buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
INFERENCE_LATENCY = Histogram("gridintel_model_inference_seconds", "Ensemble inference latency per record",
                              buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1))
ALERTS_RAISED = Counter("gridintel_alerts_raised_total", "Alerts raised by the replay engine", ["category"])
REPLAY_CURSOR = Gauge("gridintel_replay_cursor", "Replay cursor position")
ERRORS = Counter("gridintel_errors_total", "Unhandled errors", ["type"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
                   "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
                   "request_id": request_id_var.get()}
        for k in ("method", "path", "status", "duration_ms", "client", "event", "user", "detail"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    for name in ("uvicorn.access",):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = False


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
