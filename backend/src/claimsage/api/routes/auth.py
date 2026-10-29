
"""Login and current-employee endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.core.config import get_settings
from claimsage.db.models import AuditEvent, Employee
from claimsage.db.session import get_db
from claimsage.schemas.auth import (
    CurrentEmployeeResponse,
    LoginRequest,
    TokenResponse,
)
from claimsage.services.auth import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    session: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate an employee and return a short-lived access token."""

    email = str(request.email).strip().lower()

    employee = session.scalar(
        select(Employee).where(func.lower(Employee.email) == email)
    )

    authenticated = False

    if employee is not None and employee.password_hash is not None:
        authenticated = verify_password(
            request.password,
            employee.password_hash,
        )

    if not authenticated or employee is None:
        session.add(
            AuditEvent(
                actor_employee_id=None,
                action="login_failed",
                resource_type="employee_authentication",
                details="Invalid credentials.",
            )
        )
        session.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(employee.id)

    session.add(
        AuditEvent(
            actor_employee_id=employee.id,
            action="login_succeeded",
            resource_type="employee_authentication",
            resource_id=str(employee.id),
            details="Employee authenticated successfully.",
        )
    )
    session.commit()

    return TokenResponse(
        access_token=token,
        expires_in=get_settings().access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=CurrentEmployeeResponse)
def get_me(
    employee: Employee = Depends(get_current_employee),
) -> CurrentEmployeeResponse:
    """Return safe details for the authenticated employee."""

    return CurrentEmployeeResponse(
        id=str(employee.id),
        email=employee.email,
        display_name=employee.display_name,
        role=employee.role.value,
        team_id=employee.team_id,
    )
