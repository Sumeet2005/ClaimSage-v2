"""ASGI middleware for enforcing policy-document upload request limits."""

import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.responses import JSONResponse

UPLOAD_PATH = "/api/v1/policies/documents"
SPOOL_MEMORY_BYTES = 1024 * 1024
REPLAY_CHUNK_BYTES = 256 * 1024


class UploadSizeLimitMiddleware:
    """Enforce an upload request limit using bounded temporary-file spooling."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        max_body_bytes: int,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive.")

        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != UPLOAD_PATH
        ):
            await self.app(scope, receive, send)
            return

        content_length = self._get_content_length(scope)

        if content_length is not None and content_length > self.max_body_bytes:
            await self._send_too_large(scope, receive, send)
            return

        spool = tempfile.SpooledTemporaryFile(
            max_size=SPOOL_MEMORY_BYTES,
            mode="w+b",
        )

        try:
            received_bytes = 0

            while True:
                message = await receive()

                if message["type"] == "http.disconnect":
                    return

                if message["type"] != "http.request":
                    continue

                body = message.get("body", b"")
                received_bytes += len(body)

                if received_bytes > self.max_body_bytes:
                    await self._send_too_large(scope, receive, send)
                    return

                if body:
                    await anyio.to_thread.run_sync(spool.write, body)

                if not message.get("more_body", False):
                    break

            await anyio.to_thread.run_sync(spool.seek, 0)

            replay_finished = False

            async def replay_receive() -> dict[str, Any]:
                nonlocal replay_finished

                if replay_finished:
                    return await receive()

                chunk = await anyio.to_thread.run_sync(
                    spool.read,
                    REPLAY_CHUNK_BYTES,
                )

                if chunk:
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": True,
                    }

                replay_finished = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            await self.app(scope, replay_receive, send)

        finally:
            await anyio.to_thread.run_sync(spool.close)

    @staticmethod
    def _get_content_length(scope: dict[str, Any]) -> int | None:
        """Return a valid non-negative Content-Length, if supplied."""
        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]

        if len(values) != 1:
            return None

        try:
            length = int(values[0])
        except (TypeError, ValueError):
            return None

        return length if length >= 0 else None

    @staticmethod
    async def _send_too_large(
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "detail": "Upload request exceeds the configured size limit."
            },
        )
        await response(scope, receive, send)
