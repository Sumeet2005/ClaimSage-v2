"""Observability helpers: structured JSON logging, correlation IDs, and context propagation."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variables for tracing and correlation across async and threaded execution
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)
investigation_id_ctx: ContextVar[str | None] = ContextVar("investigation_id", default=None)
worker_id_ctx: ContextVar[str | None] = ContextVar("worker_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as structured, single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject context variables if present
        cid = correlation_id_ctx.get() or getattr(record, "correlation_id", None)
        if cid:
            log_payload["correlation_id"] = str(cid)

        inv_id = investigation_id_ctx.get() or getattr(record, "investigation_id", None)
        if inv_id:
            log_payload["investigation_id"] = str(inv_id)

        wid = worker_id_ctx.get() or getattr(record, "worker_id", None)
        if wid:
            log_payload["worker_id"] = str(wid)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """ASGI middleware to propagate or generate X-Request-ID and correlation context."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        incoming_cid = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        correlation_id = incoming_cid.strip() if incoming_cid and incoming_cid.strip() else str(uuid4())

        # Set in contextvar and request state
        token = correlation_id_ctx.set(correlation_id)
        request.state.correlation_id = correlation_id

        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = correlation_id
            return response
        finally:
            correlation_id_ctx.reset(token)
