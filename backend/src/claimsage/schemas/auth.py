
"""Pydantic schemas for employee authentication."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Credentials submitted by an employee."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Validate an email-shaped identifier, including internal domains."""
        value = value.strip().lower()

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")

        return value


class TokenResponse(BaseModel):
    """Access token returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentEmployeeResponse(BaseModel):
    """Safe employee details for the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: str
    team_id: str | None
