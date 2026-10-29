"""Seed ClaimSage with synthetic demo employees and claims."""

from sqlalchemy import select

from claimsage.db.models import AuditEvent, Claim, Employee, EmployeeRole
from claimsage.db.session import SessionLocal


DEMO_EMPLOYEES = [
    {
        "email": "alex.adjuster@claimsage.local",
        "display_name": "Alex Morgan",
        "role": EmployeeRole.CLAIMS_ADJUSTER,
        "team_id": "property-team",
    },
    {
        "email": "taylor.adjuster@claimsage.local",
        "display_name": "Taylor Reed",
        "role": EmployeeRole.CLAIMS_ADJUSTER,
        "team_id": "auto-team",
    },
    {
        "email": "jordan.lead@claimsage.local",
        "display_name": "Jordan Lee",
        "role": EmployeeRole.TEAM_LEAD,
        "team_id": "property-team",
    },
    {
        "email": "casey.policy@claimsage.local",
        "display_name": "Casey Patel",
        "role": EmployeeRole.POLICY_SPECIALIST,
        "team_id": "policy-team",
    },
    {
        "email": "admin@claimsage.local",
        "display_name": "ClaimSage Demo Admin",
        "role": EmployeeRole.ADMIN,
        "team_id": None,
    },
]

DEMO_CLAIMS = [
    {
        "claim_number": "CLM-DEMO-1001",
        "claimant_name": "Morgan Example",
        "claim_type": "property",
        "status": "under_review",
        "team_id": "property-team",
        "summary": (
            "Synthetic water-damage claim. The inspection report is available; "
            "proof of ownership still requires review."
        ),
        "assignee_email": "alex.adjuster@claimsage.local",
    },
    {
        "claim_number": "CLM-DEMO-1002",
        "claimant_name": "Riley Sample",
        "claim_type": "property",
        "status": "documents_pending",
        "team_id": "property-team",
        "summary": (
            "Synthetic storm-damage claim. Repair estimates and photographs "
            "are recorded as received; the checklist needs verification."
        ),
        "assignee_email": "jordan.lead@claimsage.local",
    },
    {
        "claim_number": "CLM-DEMO-2001",
        "claimant_name": "Jamie Fiction",
        "claim_type": "auto",
        "status": "under_review",
        "team_id": "auto-team",
        "summary": (
            "Synthetic vehicle-damage claim. A repair estimate is present; "
            "the incident statement needs review."
        ),
        "assignee_email": "taylor.adjuster@claimsage.local",
    },
]


def seed_demo_data() -> None:
    """Insert demo records without duplicating existing records."""
    with SessionLocal.begin() as session:
        employees_by_email: dict[str, Employee] = {}

        for employee_data in DEMO_EMPLOYEES:
            email = employee_data["email"]
            employee = session.scalar(
                select(Employee).where(Employee.email == email)
            )

            if employee is None:
                employee = Employee(**employee_data)
                session.add(employee)
                session.flush()

            employees_by_email[email] = employee

        for claim_data in DEMO_CLAIMS:
            claim_number = claim_data["claim_number"]
            existing_claim = session.scalar(
                select(Claim).where(Claim.claim_number == claim_number)
            )

            if existing_claim is not None:
                continue

            claim_values = {
                key: value
                for key, value in claim_data.items()
                if key != "assignee_email"
            }
            claim = Claim(
                **claim_values,
                assigned_employee_id=employees_by_email[
                    claim_data["assignee_email"]
                ].id,
            )
            session.add(claim)

        session.add(
            AuditEvent(
                action="demo_seed_executed",
                resource_type="demo_dataset",
                resource_id="initial-demo-data",
                details="Synthetic demo seed script executed.",
            )
        )

    print("ClaimSage synthetic demo data seeded successfully.")
    print(f"Employees configured: {len(DEMO_EMPLOYEES)}")
    print(f"Claims configured: {len(DEMO_CLAIMS)}")


if __name__ == "__main__":
    seed_demo_data()