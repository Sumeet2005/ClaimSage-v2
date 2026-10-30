import pytest

from claimsage.core.upload_limits import (
    UPLOAD_PATH,
    UploadSizeLimitMiddleware,
)


def make_scope(
    path: str = UPLOAD_PATH,
    method: str = "POST",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }


async def make_receive(
    messages: list[dict],
):
    remaining = iter(messages)

    async def receive() -> dict:
        return next(
            remaining,
            {"type": "http.request", "body": b"", "more_body": False},
        )

    return receive


async def make_send_collector() -> tuple[list[dict], object]:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    return sent, send


@pytest.mark.anyio
async def test_rejects_content_length_above_limit() -> None:
    app_called = False

    async def app(scope, receive, send) -> None:
        nonlocal app_called
        app_called = True

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=10)
    scope = make_scope(headers=[(b"content-length", b"11")])
    receive = await make_receive([])
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert not app_called
    assert sent[0]["status"] == 413


@pytest.mark.anyio
async def test_rejects_streamed_body_above_limit() -> None:
    async def app(scope, receive, send) -> None:
        await receive()
        await receive()

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=10)
    scope = make_scope()
    receive = await make_receive(
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": False},
        ]
    )
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert sent[0]["status"] == 413


@pytest.mark.anyio
async def test_accepts_body_exactly_at_limit() -> None:
    app_received = []

    async def app(scope, receive, send) -> None:
        message = await receive()
        app_received.append(message["body"])

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=10)
    scope = make_scope()
    receive = await make_receive(
        [{"type": "http.request", "body": b"1234567890", "more_body": False}]
    )
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert app_received == [b"1234567890"]
    assert sent == []


@pytest.mark.anyio
async def test_does_not_limit_other_routes() -> None:
    app_called = False

    async def app(scope, receive, send) -> None:
        nonlocal app_called
        app_called = True

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=10)
    scope = make_scope(path="/api/v1/claims")
    receive = await make_receive([])
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert app_called
    assert sent == []


@pytest.mark.anyio
async def test_oversized_body_is_rejected_before_app_is_invoked() -> None:
    app_called = False

    async def app(scope, receive, send) -> None:
        nonlocal app_called
        app_called = True

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=5)
    scope = make_scope()
    receive = await make_receive(
        [{"type": "http.request", "body": b"123456", "more_body": False}]
    )
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert not app_called
    assert len(sent) == 2
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert sent[1]["type"] == "http.response.body"


@pytest.mark.anyio
async def test_spool_is_closed_after_successful_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claimsage.core.upload_limits as upload_limits

    created_spools = []
    original_factory = upload_limits.tempfile.SpooledTemporaryFile

    def tracking_factory(*args, **kwargs):
        spool = original_factory(*args, **kwargs)
        created_spools.append(spool)
        return spool

    monkeypatch.setattr(
        upload_limits.tempfile,
        "SpooledTemporaryFile",
        tracking_factory,
    )

    async def app(scope, receive, send) -> None:
        message = await receive()
        assert message["body"] == b"synthetic upload"

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=100)
    scope = make_scope()
    receive = await make_receive(
        [
            {
                "type": "http.request",
                "body": b"synthetic upload",
                "more_body": False,
            }
        ]
    )
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert len(created_spools) == 1
    assert created_spools[0].closed
    assert sent == []


@pytest.mark.anyio
async def test_spool_is_closed_after_oversized_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claimsage.core.upload_limits as upload_limits

    created_spools = []
    original_factory = upload_limits.tempfile.SpooledTemporaryFile

    def tracking_factory(*args, **kwargs):
        spool = original_factory(*args, **kwargs)
        created_spools.append(spool)
        return spool

    monkeypatch.setattr(
        upload_limits.tempfile,
        "SpooledTemporaryFile",
        tracking_factory,
    )

    async def app(scope, receive, send) -> None:
        raise AssertionError("Downstream application must not be invoked.")

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=5)
    scope = make_scope()
    receive = await make_receive(
        [
            {
                "type": "http.request",
                "body": b"oversized",
                "more_body": False,
            }
        ]
    )
    sent, send = await make_send_collector()

    await middleware(scope, receive, send)

    assert len(created_spools) == 1
    assert created_spools[0].closed
    assert sent[0]["status"] == 413

@pytest.mark.anyio
async def test_replay_receiver_preserves_client_disconnect() -> None:
    messages = iter(
        [
            {
                "type": "http.request",
                "body": b"synthetic upload",
                "more_body": False,
            },
            {"type": "http.disconnect"},
        ]
    )

    async def receive() -> dict:
        return next(messages)

    received = []

    async def app(scope, replay_receive, send) -> None:
        received.append(await replay_receive())
        received.append(await replay_receive())
        received.append(await replay_receive())

    middleware = UploadSizeLimitMiddleware(app, max_body_bytes=100)

    await middleware(make_scope(), receive, lambda message: _send_noop(message))

    assert received[0]["body"] == b"synthetic upload"
    assert received[0]["more_body"] is True
    assert received[1]["body"] == b""
    assert received[1]["more_body"] is False
    assert received[2]["type"] == "http.disconnect"


async def _send_noop(message: dict) -> None:
    return None

