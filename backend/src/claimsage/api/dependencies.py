
"""FastAPI dependencies for authenticated employee requests."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import Employee
from claimsage.db.session import get_db
from claimsage.services.auth import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_employee(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> Employee:
    """Validate a Bearer token and load the employee from the database."""

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        employee_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None

    employee = session.scalar(
        select(Employee).where(Employee.id == employee_id)
    )

    if employee is None:
        raise unauthorized

    return employee
