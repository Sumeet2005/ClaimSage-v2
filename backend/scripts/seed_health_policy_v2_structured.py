"""Seed structured clauses, coverages, and exclusions for Policy v2 idempotently.

Target Policy:
- ID: 702ed921-5a3b-462e-889c-4a1957690ea4
- Product: Demo Health Secure Plan
- Version: v2.0
- Identifier: DEMO-HEALTH-SECURE-2026
"""

from decimal import Decimal
import logging
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from claimsage.db.models import (
    Employee,
    PolicyChunk,
    PolicyClause,
    PolicyCoverage,
    PolicyDocument,
    PolicyExclusion,
)
from claimsage.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

POLICY_ID = uuid.UUID("702ed921-5a3b-462e-889c-4a1957690ea4")


def seed_structured_policy_data() -> None:
    session = SessionLocal()
    try:
        # 1. Verify policy document
        policy = session.scalar(select(PolicyDocument).where(PolicyDocument.id == POLICY_ID))
        if not policy:
            logger.error("Policy %s not found in database!", POLICY_ID)
            sys.exit(1)

        logger.info(
            "Found Policy: %s (v%s, ID: %s)",
            policy.product_name,
            policy.policy_version,
            policy.id,
        )

        # 2. Get admin employee for verification
        admin = session.scalar(
            select(Employee).where(Employee.email == "admin@claimsage.local")
        )
        admin_id = admin.id if admin else policy.uploaded_by_employee_id
        now_utc = datetime.now(timezone.utc)

        # 3. Retrieve chunks for policy v2
        chunks = session.scalars(
            select(PolicyChunk)
            .where(PolicyChunk.document_id == POLICY_ID)
            .order_by(PolicyChunk.page_number, PolicyChunk.chunk_index)
        ).all()

        if len(chunks) < 6:
            logger.error("Expected at least 6 chunks for policy v2, found %d", len(chunks))
            sys.exit(1)

        chunk_map = {(c.page_number, c.chunk_index): c for c in chunks}

        # 4. Idempotently seed PolicyClauses (1 per chunk due to source_chunk_id unique constraint)
        clause_definitions = [
            {
                "page": 1,
                "index": 0,
                "identifier": "SEC-1-OVERVIEW",
                "category": "definition",
                "title": "Policy Overview and Definitions",
                "text": chunk_map[(1, 0)].text,
            },
            {
                "page": 1,
                "index": 1,
                "identifier": "SEC-3-BENEFITS",
                "category": "coverage",
                "title": "Benefits and Inpatient Coverage",
                "text": chunk_map[(1, 1)].text,
            },
            {
                "page": 1,
                "index": 2,
                "identifier": "SEC-3.5-ROOM-RENT",
                "category": "limit",
                "title": "Post-Hospitalization and Room Rent Limit",
                "text": chunk_map[(1, 2)].text,
            },
            {
                "page": 2,
                "index": 0,
                "identifier": "SEC-4-WAITING-PERIODS",
                "category": "condition",
                "title": "Waiting Periods and Benefit Limits",
                "text": chunk_map[(2, 0)].text,
            },
            {
                "page": 2,
                "index": 1,
                "identifier": "SEC-6-EXCLUSIONS",
                "category": "exclusion",
                "title": "General Exclusions and Claim Documents",
                "text": chunk_map[(2, 1)].text,
            },
            {
                "page": 2,
                "index": 2,
                "identifier": "SEC-8-WORKFLOW",
                "category": "condition",
                "title": "Claim Review Workflow and Privacy",
                "text": chunk_map[(2, 2)].text,
            },
        ]

        inserted_clauses = 0
        for cdef in clause_definitions:
            chunk = chunk_map.get((cdef["page"], cdef["index"]))
            if not chunk:
                continue

            existing_clause = session.scalar(
                select(PolicyClause).where(PolicyClause.source_chunk_id == chunk.id)
            )
            if existing_clause:
                logger.info("Clause for chunk (%d, %d) already exists: %s", cdef["page"], cdef["index"], existing_clause.clause_identifier)
                continue

            clause = PolicyClause(
                id=uuid.uuid4(),
                document_id=POLICY_ID,
                source_chunk_id=chunk.id,
                clause_identifier=cdef["identifier"],
                clause_category=cdef["category"],
                title=cdef["title"],
                clause_text=cdef["text"],
                source_page_number=cdef["page"],
                verification_status="verified",
                verified_by_employee_id=admin_id,
                verified_at=now_utc,
            )
            session.add(clause)
            inserted_clauses += 1

        # 5. Idempotently seed PolicyCoverages
        coverage_definitions = [
            {
                "name": "Inpatient Hospitalization",
                "category": "inpatient",
                "benefit_limit": Decimal("500000.00"),
                "deductible": Decimal("0.00"),
                "co_pay_percentage": Decimal("0.00"),
                "waiting_period_days": 30,
                "description": (
                    "Eligible medical expenses for medically necessary inpatient hospitalization "
                    "requiring at least 24 consecutive hours stay, covered up to the available sum insured "
                    "of INR 500,000."
                ),
            },
            {
                "name": "Day-care Procedures",
                "category": "daycare",
                "benefit_limit": Decimal("500000.00"),
                "deductible": Decimal("0.00"),
                "co_pay_percentage": Decimal("0.00"),
                "waiting_period_days": 30,
                "description": (
                    "Listed medically necessary procedures that do not require a 24-hour hospital stay "
                    "when performed at an eligible hospital or day-care centre."
                ),
            },
            {
                "name": "Pre-Hospitalization Expenses",
                "category": "pre_hospitalization",
                "benefit_limit": None,
                "deductible": None,
                "co_pay_percentage": None,
                "waiting_period_days": 30,
                "description": (
                    "Eligible medical expenses incurred during the 30 days immediately before an admissible "
                    "hospitalization when relating to the same condition and supported by bills/prescriptions."
                ),
            },
            {
                "name": "Post-Hospitalization Expenses",
                "category": "post_hospitalization",
                "benefit_limit": None,
                "deductible": None,
                "co_pay_percentage": None,
                "waiting_period_days": 30,
                "description": (
                    "Eligible medical expenses incurred during the 60 days immediately after an admissible "
                    "hospitalization when relating to the same condition and supported by bills/prescriptions."
                ),
            },
            {
                "name": "Room Rent Limit",
                "category": "room_rent",
                "benefit_limit": Decimal("5000.00"),
                "deductible": Decimal("0.00"),
                "co_pay_percentage": Decimal("0.00"),
                "waiting_period_days": 30,
                "description": (
                    "The eligible room rent limit under this policy is INR 5,000 per day as stated in "
                    "Section 3.5 and Section 5."
                ),
            },
        ]

        inserted_coverages = 0
        for cov in coverage_definitions:
            existing_cov = session.scalar(
                select(PolicyCoverage).where(
                    PolicyCoverage.document_id == POLICY_ID,
                    PolicyCoverage.coverage_name == cov["name"],
                )
            )
            if existing_cov:
                logger.info("Coverage already exists: %s", cov["name"])
                continue

            coverage = PolicyCoverage(
                id=uuid.uuid4(),
                document_id=POLICY_ID,
                coverage_name=cov["name"],
                coverage_category=cov["category"],
                benefit_limit=cov["benefit_limit"],
                deductible=cov["deductible"],
                co_pay_percentage=cov["co_pay_percentage"],
                waiting_period_days=cov["waiting_period_days"],
                description=cov["description"],
                is_optional=False,
            )
            session.add(coverage)
            inserted_coverages += 1

        # 6. Idempotently seed PolicyExclusions
        exclusion_definitions = [
            {
                "code": "EXCL-WAIT-30D",
                "title": "Initial 30-Day Illness Waiting Period",
                "description": (
                    "A 30-day initial waiting period applies from the policy start date for illnesses, "
                    "except treatment required due to an accident, subject to policy terms."
                ),
                "waiting_period_months": 1,
                "type": "waiting_period",
            },
            {
                "code": "EXCL-PED-36M",
                "title": "Pre-Existing Diseases Waiting Period",
                "description": (
                    "Pre-existing diseases are subject to an illustrative waiting period of 36 months of continuous coverage."
                ),
                "waiting_period_months": 36,
                "type": "waiting_period",
            },
            {
                "code": "EXCL-SPEC-24M",
                "title": "Specific Listed Conditions Waiting Period",
                "description": (
                    "Certain listed conditions and procedures have a separate 24-month waiting period."
                ),
                "waiting_period_months": 24,
                "type": "specified_illness",
            },
            {
                "code": "EXCL-PERM-NONMED",
                "title": "Non-Medically Necessary Treatment",
                "description": (
                    "Expenses for non-medically necessary treatment or hospitalizations are not covered."
                ),
                "waiting_period_months": None,
                "type": "permanent",
            },
            {
                "code": "EXCL-PERM-COSMETIC",
                "title": "Cosmetic or Aesthetic Treatment",
                "description": (
                    "Cosmetic or aesthetic treatment is excluded unless medically necessary due to an accident, "
                    "burn, or other qualifying condition under the policy."
                ),
                "waiting_period_months": None,
                "type": "permanent",
            },
            {
                "code": "EXCL-PERM-CONVENIENCE",
                "title": "Personal Convenience Items",
                "description": (
                    "Non-medical personal convenience items are excluded unless specifically listed as covered."
                ),
                "waiting_period_months": None,
                "type": "permanent",
            },
        ]

        inserted_exclusions = 0
        for excl in exclusion_definitions:
            existing_excl = session.scalar(
                select(PolicyExclusion).where(
                    PolicyExclusion.document_id == POLICY_ID,
                    PolicyExclusion.exclusion_code == excl["code"],
                )
            )
            if existing_excl:
                logger.info("Exclusion already exists: %s", excl["code"])
                continue

            exclusion = PolicyExclusion(
                id=uuid.uuid4(),
                document_id=POLICY_ID,
                exclusion_code=excl["code"],
                title=excl["title"],
                description=excl["description"],
                waiting_period_months=excl["waiting_period_months"],
                exclusion_type=excl["type"],
            )
            session.add(exclusion)
            inserted_exclusions += 1

        session.commit()
        logger.info(
            "Successfully seeded structured policy data for v2: "
            "%d clauses inserted, %d coverages inserted, %d exclusions inserted.",
            inserted_clauses,
            inserted_coverages,
            inserted_exclusions,
        )

    except Exception:
        session.rollback()
        logger.exception("Failed to seed structured policy data")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_structured_policy_data()
