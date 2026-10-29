"""Initial ClaimSage database models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from claimsage.db.base import Base


class EmployeeRole(StrEnum):
    """Roles used by ClaimSage authorization policies."""

    CLAIMS_ADJUSTER = "claims_adjuster"
    TEAM_LEAD = "team_lead"
    POLICY_SPECIALIST = "policy_specialist"
    ADMIN = "admin"


class Employee(Base):
    """Internal employee account."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(200))

    # Nullable so existing synthetic employee records remain compatible.
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    role: Mapped[EmployeeRole] = mapped_column(
        Enum(EmployeeRole, name="employee_role"),
        default=EmployeeRole.CLAIMS_ADJUSTER,
        nullable=False,
    )
    team_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Claim(Base):
    """Synthetic insurance claim record."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    claim_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
    )
    claimant_name: Mapped[str] = mapped_column(String(200))
    claim_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(50),
        default="under_review",
        nullable=False,
    )
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    team_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    assigned_employee: Mapped[Employee | None] = relationship()


class AuditEvent(Base):
    """Record of important application actions."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )