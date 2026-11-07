"""In-memory rate limiting middleware for API protection without external broker dependencies."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def get_client_ip(request: Request, trusted_proxies: set[str] | None = None) -> str:
    """Extract client IP, inspecting proxy headers only when request arrives from a trusted proxy."""
    client_host = request.client.host if request.client else "unknown"
    if trusted_proxies is None:
        trusted_proxies = {"127.0.0.1", "::1", "localhost"}

    # Consider localhost and private container networks (Docker bridge) as trusted proxies
    is_trusted = (
        client_host in trusted_proxies
        or client_host.startswith(("127.", "10.", "172.", "192.168."))
    )

    if is_trusted:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip and real_ip.strip():
            return real_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded and forwarded.strip():
            return forwarded.split(",")[0].strip()

    return client_host


class InMemoryRateLimiter:
    """Sliding window rate limiter with bounded memory and periodic expiration sweep."""

    def __init__(
        self,
        default_limit: int = 120,
        window_seconds: int = 60,
        max_tracked_clients: int = 10000,
    ) -> None:
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.max_tracked_clients = max_tracked_clients
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_sweep = time.time()

    def is_allowed(self, client_key: str, limit: int | None = None) -> tuple[bool, int]:
        max_requests = limit if limit is not None else self.default_limit
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            # Periodic sweep to prevent unbounded memory growth from ephemeral IPs
            if now - self._last_sweep > 60.0 or len(self._hits) > self.max_tracked_clients:
                self._sweep_expired(window_start)
                self._last_sweep = now

            timestamps = [ts for ts in self._hits[client_key] if ts > window_start]
            if len(timestamps) >= max_requests:
                # Disallowed; calculate seconds until oldest hit expires
                retry_after = max(1, int(timestamps[0] + self.window_seconds - now))
                self._hits[client_key] = timestamps
                return False, retry_after

            timestamps.append(now)
            self._hits[client_key] = timestamps
            return True, 0

    def _sweep_expired(self, window_start: float) -> None:
        """Prune inactive client buckets from dictionary."""
        expired_keys = [
            key
            for key, timestamps in self._hits.items()
            if not timestamps or timestamps[-1] <= window_start
        ]
        for key in expired_keys:
            del self._hits[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware to rate limit incoming API requests."""

    # Specific routes with stricter limits
    ROUTE_LIMITS = {
        "/api/v1/auth/token": 15,  # 15 requests/min per IP to prevent credential brute forcing
    }

    def __init__(
        self,
        app: Any,
        default_limit: int = 120,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.limiter = InMemoryRateLimiter(default_limit=default_limit, window_seconds=60)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Skip rate-limiting for health check endpoints
        if request.url.path.startswith("/health"):
            return await call_next(request)

        client_host = get_client_ip(request)
        path = request.url.path
        limit = self.ROUTE_LIMITS.get(path)

        client_key = f"{client_host}:{path if limit is not None else 'general'}"
        allowed, retry_after = self.limiter.is_allowed(client_key, limit=limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down and try again.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
