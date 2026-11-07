import smtplib
from email.message import EmailMessage
from uuid import uuid4

import pytest

from claimsage.services.notifications import (
    NotificationDeliveryError,
    NotificationEvent,
    SandboxEmailTransport,
    dispatch_notification,
    enqueue_notification,
    render_notification,
    send_with_bounded_retries,
)


@pytest.mark.parametrize("event", list(NotificationEvent))
def test_notification_templates_are_generic_and_use_secure_links(
    event: NotificationEvent,
) -> None:
    mail = render_notification(
        event=event,
        recipient="employee@example.invalid",
        sender="claimsage@example.invalid",
        application_base_url="https://claims.example.invalid",
        application_path="/claims/synthetic-claim",
    )

    assert mail.subject.startswith("ClaimSage:")
    assert "https://claims.example.invalid/claims/synthetic-claim" in (
        mail.text_body
    )
    assert "https://claims.example.invalid/claims/synthetic-claim" in (
        mail.html_body
    )
    assert "diagnosis" not in mail.text_body.casefold()
    assert "policy number" not in mail.text_body.casefold()


@pytest.mark.parametrize(
    "path",
    [
        "https://outside.example/",
        "//outside.example/",
        "/claims/../admin",
        "/claims/\r\nBcc:outside@example.invalid",
    ],
)
def test_notification_template_rejects_untrusted_paths(path: str) -> None:
    with pytest.raises(ValueError):
        render_notification(
            event=NotificationEvent.REVIEW_COMPLETED,
            recipient="employee@example.invalid",
            sender="claimsage@example.invalid",
            application_base_url="https://claims.example.invalid",
            application_path=path,
        )


def test_sandbox_transport_accepts_without_network_delivery() -> None:
    message = EmailMessage()
    message["To"] = "employee@example.invalid"
    message.set_content("Synthetic sandbox message.")

    assert send_with_bounded_retries(
        SandboxEmailTransport(),
        message,
    ) == 1


def test_delivery_retries_transient_errors_with_a_fixed_limit() -> None:
    class TemporaryTransport:
        def __init__(self) -> None:
            self.attempts = 0

        def send(self, _message: EmailMessage) -> None:
            self.attempts += 1
            if self.attempts < 3:
                raise ConnectionError("synthetic transport failure")

    transport = TemporaryTransport()
    sleeps: list[float] = []
    message = EmailMessage()

    assert send_with_bounded_retries(
        transport,
        message,
        sleep=sleeps.append,
    ) == 3
    assert transport.attempts == 3
    assert len(sleeps) == 2


def test_delivery_stops_on_authentication_failure_without_retry() -> None:
    class UnauthorizedTransport:
        def __init__(self) -> None:
            self.attempts = 0

        def send(self, _message: EmailMessage) -> None:
            self.attempts += 1
            raise smtplib.SMTPAuthenticationError(535, b"synthetic failure")

    transport = UnauthorizedTransport()

    with pytest.raises(NotificationDeliveryError) as error:
        send_with_bounded_retries(
            transport,
            EmailMessage(),
            sleep=lambda _delay: None,
        )
    assert error.value.attempts == 1
    assert error.value.error_type == "SMTPAuthenticationError"
    assert transport.attempts == 1


def test_enqueue_uses_stable_event_recipient_idempotency_key() -> None:
    notification_id = uuid4()

    class SessionStub:
        def scalar(self, _statement):
            return notification_id

    recipient_id = uuid4()
    resource_id = uuid4()
    result = enqueue_notification(
        SessionStub(),
        event=NotificationEvent.HUMAN_REVIEW_REQUIRED,
        recipient_employee_id=recipient_id,
        resource_id=resource_id,
        application_path=f"/claims/{resource_id}",
    )

    assert result == notification_id


class DeliverySessionStub:
    def __init__(self, delivery) -> None:
        self.delivery = delivery
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def scalar(self, _statement):
        return self.delivery

    def get(self, _model, _employee_id):
        return type("Recipient", (), {"email": "employee@example.invalid"})()

    def commit(self) -> None:
        self.commits += 1


@pytest.mark.parametrize(
    ("backend", "expected_status"),
    [("sandbox", "sandboxed"), ("smtp", "delivered")],
)
def test_dispatch_persists_sandbox_or_success_status(
    backend: str,
    expected_status: str,
) -> None:
    delivery = type(
        "Delivery",
        (),
        {
            "status": "pending",
            "event_type": NotificationEvent.REVIEW_COMPLETED.value,
            "application_path": "/claims/synthetic-claim",
            "recipient_employee_id": uuid4(),
            "attempt_count": 0,
            "last_error_type": None,
            "delivered_at": None,
        },
    )()
    session = DeliverySessionStub(delivery)
    settings = type(
        "Settings",
        (),
        {
            "email_backend": backend,
            "email_from_address": "claimsage@example.invalid",
            "email_app_base_url": "https://claims.example.invalid",
        },
    )()
    class SuccessfulTransport:
        def send(self, _message: EmailMessage) -> None:
            return None

    dispatch_notification(
        uuid4(),
        session_factory=lambda: session,
        settings=settings,
        transport_factory=(
            (lambda _settings: SandboxEmailTransport())
            if backend == "sandbox"
            else (lambda _settings: SuccessfulTransport())
        ),
    )

    assert delivery.status == expected_status
    assert delivery.attempt_count == 1
    assert session.commits == 2


def test_dispatch_records_failure_without_exposing_provider_text() -> None:
    delivery = type(
        "Delivery",
        (),
        {
            "status": "pending",
            "event_type": NotificationEvent.REVIEW_COMPLETED.value,
            "application_path": "/claims/synthetic-claim",
            "recipient_employee_id": uuid4(),
            "attempt_count": 0,
            "last_error_type": None,
            "delivered_at": None,
        },
    )()
    session = DeliverySessionStub(delivery)
    settings = type(
        "Settings",
        (),
        {
            "email_backend": "smtp",
            "email_from_address": "claimsage@example.invalid",
            "email_app_base_url": "https://claims.example.invalid",
        },
    )()

    class UnauthorizedTransport:
        def send(self, _message: EmailMessage) -> None:
            raise smtplib.SMTPAuthenticationError(
                535,
                b"synthetic private server response",
            )

    dispatch_notification(
        uuid4(),
        session_factory=lambda: session,
        settings=settings,
        transport_factory=lambda _settings: UnauthorizedTransport(),
    )

    assert delivery.status == "failed"
    assert delivery.attempt_count == 1
    assert delivery.last_error_type == "SMTPAuthenticationError"
