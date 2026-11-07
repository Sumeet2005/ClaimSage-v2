"""Idempotent, privacy-preserving email notifications."""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from enum import StrEnum
from html import escape
from typing import Protocol
from urllib.parse import unquote, urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from claimsage.db.models import Employee, NotificationDelivery

logger = logging.getLogger(__name__)
_MAX_DELIVERY_ATTEMPTS = 3


class NotificationEvent(StrEnum):
    CLAIM_RECEIVED = "claim_received"
    INVESTIGATION_COMPLETED = "investigation_completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    ADDITIONAL_EVIDENCE_REQUIRED = "additional_evidence_required"
    REVIEW_COMPLETED = "review_completed"


@dataclass(frozen=True)
class NotificationMail:
    recipient: str
    sender: str
    subject: str
    text_body: str
    html_body: str


class EmailTransport(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class NotificationDeliveryError(RuntimeError):
    def __init__(self, *, attempts: int, error_type: str) -> None:
        super().__init__("The notification could not be delivered.")
        self.attempts = attempts
        self.error_type = error_type


class SandboxEmailTransport:
    """Accept an email in sandbox mode without network delivery or logging."""

    def send(self, _message: EmailMessage) -> None:
        return None


class SMTPEmailTransport:
    def __init__(self, settings: object) -> None:
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        host = self.settings.email_smtp_host
        port = self.settings.email_smtp_port
        timeout = 10.0
        context = ssl.create_default_context()

        if port == 465:
            with smtplib.SMTP_SSL(
                host,
                port,
                timeout=timeout,
                context=context,
            ) as client:
                self._authenticate(client)
                client.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=timeout) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            self._authenticate(client)
            client.send_message(message)

    def _authenticate(self, client: smtplib.SMTP) -> None:
        username = self.settings.email_smtp_username
        password = self.settings.email_smtp_password
        if username is not None and password is not None:
            client.login(
                username.get_secret_value(),
                password.get_secret_value(),
            )


def render_notification(
    *,
    event: NotificationEvent,
    recipient: str,
    sender: str,
    application_base_url: str,
    application_path: str,
) -> NotificationMail:
    """Render a generic secure-link notification with no claim contents."""

    parsed_path = urlsplit(application_path)
    if (
        not application_path.startswith("/")
        or application_path.startswith("//")
        or parsed_path.scheme
        or parsed_path.netloc
        or "\r" in unquote(application_path)
        or "\n" in unquote(application_path)
        or any(
            segment in {".", ".."}
            for segment in unquote(parsed_path.path).split("/")
        )
    ):
        raise ValueError("Notification application path must be relative.")

    event_copy = {
        NotificationEvent.CLAIM_RECEIVED: (
            "A claim is ready for your review.",
            "Claim received",
        ),
        NotificationEvent.INVESTIGATION_COMPLETED: (
            "An investigation has finished and is available for review.",
            "Investigation completed",
        ),
        NotificationEvent.HUMAN_REVIEW_REQUIRED: (
            "An investigation requires human review.",
            "Human review required",
        ),
        NotificationEvent.ADDITIONAL_EVIDENCE_REQUIRED: (
            "Additional evidence has been requested for an investigation.",
            "Additional evidence required",
        ),
        NotificationEvent.REVIEW_COMPLETED: (
            "A human review has been recorded.",
            "Review completed",
        ),
    }
    description, subject = event_copy[event]
    link = f"{application_base_url.rstrip('/')}{application_path}"
    safe_link = escape(link, quote=True)
    text_body = (
        f"{description}\n\n"
        f"Sign in to ClaimSage to view the secured record:\n{link}\n"
    )
    html_body = (
        "<!doctype html><html><body>"
        f"<p>{escape(description)}</p>"
        '<p><a href="'
        f"{safe_link}"
        '">Sign in to ClaimSage</a></p>'
        "</body></html>"
    )
    return NotificationMail(
        recipient=recipient,
        sender=sender,
        subject=f"ClaimSage: {subject}",
        text_body=text_body,
        html_body=html_body,
    )


def enqueue_notification(
    session: Session,
    *,
    event: NotificationEvent,
    recipient_employee_id: UUID,
    resource_id: UUID,
    application_path: str,
) -> UUID:
    """Persist one notification event, deduplicated across concurrent requests."""

    idempotency_key = (
        f"{event.value}:{resource_id}:{recipient_employee_id}"
    )
    notification_id = session.scalar(
        insert(NotificationDelivery)
        .values(
            idempotency_key=idempotency_key,
            event_type=event.value,
            recipient_employee_id=recipient_employee_id,
            resource_id=str(resource_id),
            application_path=application_path,
            status="pending",
        )
        .on_conflict_do_nothing(
            index_elements=[NotificationDelivery.idempotency_key],
        )
        .returning(NotificationDelivery.id)
    )
    if notification_id is not None:
        return notification_id

    existing_id = session.scalar(
        select(NotificationDelivery.id).where(
            NotificationDelivery.idempotency_key == idempotency_key
        )
    )
    if existing_id is None:
        raise RuntimeError("The notification outbox record was not available.")
    return existing_id


def send_with_bounded_retries(
    transport: EmailTransport,
    message: EmailMessage,
    *,
    attempts: int = _MAX_DELIVERY_ATTEMPTS,
    sleep=time.sleep,
) -> int:
    """Retry transient SMTP errors a fixed number of times."""

    if not 1 <= attempts <= _MAX_DELIVERY_ATTEMPTS:
        raise ValueError("Notification attempts exceed the configured bound.")

    for attempt in range(1, attempts + 1):
        try:
            transport.send(message)
            return attempt
        except (
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPRecipientsRefused,
        ) as exc:
            raise NotificationDeliveryError(
                attempts=attempt,
                error_type=type(exc).__name__,
            ) from None
        except smtplib.SMTPResponseException as exc:
            if exc.smtp_code >= 500 or attempt == attempts:
                raise NotificationDeliveryError(
                    attempts=attempt,
                    error_type=type(exc).__name__,
                ) from None
        except Exception as exc:
            if attempt == attempts:
                raise NotificationDeliveryError(
                    attempts=attempt,
                    error_type=type(exc).__name__,
                ) from None

        sleep(min(0.25 * (2 ** (attempt - 1)), 1.0))

    raise NotificationDeliveryError(
        attempts=attempts,
        error_type="UnknownDeliveryError",
    )


def dispatch_notification(
    notification_id: UUID,
    *,
    session_factory=None,
    settings=None,
    transport_factory=None,
) -> None:
    """Deliver one committed outbox item and persist only safe delivery status."""

    if session_factory is None:
        from claimsage.db.session import SessionLocal

        session_factory = SessionLocal
    if settings is None:
        from claimsage.core.config import get_settings

        settings = get_settings()

    with session_factory() as session:
        delivery = session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == notification_id)
            .with_for_update()
        )
        if delivery is None:
            raise LookupError("The notification outbox item was not found.")
        if delivery.status != "pending":
            return
        delivery.status = "sending"
        session.commit()

        employee = session.get(Employee, delivery.recipient_employee_id)
        if employee is None or not employee.email:
            delivery.status = "failed"
            delivery.last_error_type = "RecipientUnavailable"
            session.commit()
            logger.warning(
                "Notification delivery failed (event=%s, reason=recipient_unavailable).",
                delivery.event_type,
            )
            return

        event = NotificationEvent(delivery.event_type)
        message_content = render_notification(
            event=event,
            recipient=employee.email,
            sender=settings.email_from_address,
            application_base_url=settings.email_app_base_url,
            application_path=delivery.application_path,
        )
        message = EmailMessage()
        message["To"] = message_content.recipient
        message["From"] = message_content.sender
        message["Subject"] = message_content.subject
        message.set_content(message_content.text_body)
        message.add_alternative(
            message_content.html_body,
            subtype="html",
        )

        if transport_factory is not None:
            transport = transport_factory(settings)
        elif settings.email_backend == "sandbox":
            transport = SandboxEmailTransport()
        else:
            transport = SMTPEmailTransport(settings)

        try:
            attempt_count = send_with_bounded_retries(
                transport,
                message,
            )
        except NotificationDeliveryError as exc:
            delivery.status = "failed"
            delivery.attempt_count = exc.attempts
            delivery.last_error_type = exc.error_type[:100]
            session.commit()
            logger.warning(
                "Notification delivery failed (event=%s, error_type=%s).",
                delivery.event_type,
                exc.error_type,
            )
            return

        delivery.attempt_count = attempt_count
        delivery.status = (
            "sandboxed"
            if settings.email_backend == "sandbox"
            else "delivered"
        )
        delivery.last_error_type = None
        if delivery.status == "delivered":
            delivery.delivered_at = datetime.now(UTC)
        session.commit()
        logger.info(
            "Notification delivery recorded (event=%s, status=%s).",
            delivery.event_type,
            delivery.status,
        )
