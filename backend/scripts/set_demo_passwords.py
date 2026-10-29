
"""Set a local demo password for synthetic ClaimSage employees."""

from getpass import getpass

from sqlalchemy import select

from claimsage.db.models import Employee
from claimsage.db.session import SessionLocal
from claimsage.services.auth import hash_password


def main() -> None:
    """Prompt for a password and update synthetic demo accounts."""
    password = getpass("Enter a demo password (minimum 12 characters): ")
    confirmation = getpass("Confirm demo password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        hashed_password = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with SessionLocal.begin() as session:
        employees = session.scalars(
            select(Employee).where(
                Employee.email.like("%@claimsage.local")
            )
        ).all()

        if not employees:
            raise SystemExit(
                "No synthetic @claimsage.local employees found. Run seed_demo.py first."
            )

        for employee in employees:
            employee.password_hash = hashed_password

        print(f"Password hash updated for {len(employees)} synthetic demo employees.")


if __name__ == "__main__":
    main()
