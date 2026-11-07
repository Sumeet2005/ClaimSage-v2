"""Register and seed structured knowledge for Health v3 and Motor v1 policies idempotently.

Policies:
1. Health v3:
   - File: docs/policies/ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf
   - Identifier: DEMO-HEALTH-SECURE-2026-V3
   - Version: 3.0
   - Product: Demo Health Secure Plan
   - Insurer: ClaimSage Synthetic Assurance Ltd. (fictional)
   - Insurance Type: health

2. Motor v1:
   - File: docs/policies/ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf
   - Identifier: DEMO-MOTOR-SECURE-2026-V1
   - Version: 1.0
   - Product: Demo Motor Secure Plan
   - Insurer: ClaimSage Synthetic General Insurance Ltd. (fictional)
   - Insurance Type: auto
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import (
    AuditEvent,
    Employee,
    PolicyChunk,
    PolicyClause,
    PolicyCoverage,
    PolicyDocument,
    PolicyExclusion,
)
from claimsage.db.session import SessionLocal
from claimsage.schemas.policies import PolicyDocumentApplicability
from claimsage.services.document_persistence import (
    DuplicatePolicyDocumentError,
    persist_policy_document,
)
from claimsage.services.policy_embedding_ingestion import (
    process_policy_document_embeddings,
)
from claimsage.services.storage import (
    generate_secure_object_key,
    get_storage_service,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


HEALTH_V3_METADATA = {
    "filename": "ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
    "policy_identifier": "DEMO-HEALTH-SECURE-2026-V3",
    "policy_version": "3.0",
    "product_name": "Demo Health Secure Plan",
    "insurer_name": "ClaimSage Synthetic Assurance Ltd. (fictional)",
    "insurance_type": "health",
    "supported_claim_types": ["health"],
    "effective_from": date(2026, 1, 1),
    "effective_to": date(2026, 12, 31),
    "clauses": [
        {
            "page": 1,
            "index": 0,
            "identifier": "SEC-1-PREAMBLE",
            "category": "definition",
            "title": "Policy Overview and Legal Preamble",
        },
        {
            "page": 1,
            "index": 1,
            "identifier": "SEC-2-SCOPE-BENEFITS",
            "category": "coverage",
            "title": "Scope of Covered Hospitalization Benefits",
        },
        {
            "page": 1,
            "index": 2,
            "identifier": "SEC-3-LIMITS-COSTSHARING",
            "category": "limit",
            "title": "Benefit Limits, Sub-limits, Room Rent and ICU Caps",
        },
        {
            "page": 2,
            "index": 0,
            "identifier": "SEC-4-WAITING-EXCLUSIONS",
            "category": "exclusion",
            "title": "Waiting Periods and Statutory Exclusions",
        },
        {
            "page": 2,
            "index": 1,
            "identifier": "SEC-5-CLAIMS-GOVERNANCE",
            "category": "condition",
            "title": "Mandatory Claim Documentation and Assistive AI Rule",
        },
    ],
    "coverages": [
        {
            "name": "Inpatient Hospitalization",
            "category": "inpatient",
            "benefit_limit": Decimal("500000.00"),
            "deductible": Decimal("0.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": 30,
            "description": (
                "Eligible medical expenses for medically necessary inpatient hospitalization "
                "requiring at least 24 consecutive hours stay, covered up to the sum insured of INR 500,000."
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
                "Listed medically necessary day-care procedures requiring less than 24 hours stay "
                "undertaken under general or local anesthesia in an eligible hospital."
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
                "Eligible medical expenses incurred during 30 days prior to admission for the same "
                "diagnosed condition resulting in hospitalization."
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
                "Eligible medical expenses incurred during 60 days following hospital discharge for the "
                "same condition resulting in hospitalization."
            ),
        },
        {
            "name": "Room Rent Limit",
            "category": "room_rent",
            "benefit_limit": Decimal("5000.00"),
            "deductible": Decimal("0.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": 30,
            "description": "Room rent capped at INR 5,000 per day as specified in Section 3.",
        },
        {
            "name": "ICU Room Charges Limit",
            "category": "icu_charges",
            "benefit_limit": Decimal("10000.00"),
            "deductible": Decimal("0.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": 30,
            "description": "Intensive Care Unit (ICU) charges capped at INR 10,000 per day as specified in Section 3.",
        },
    ],
    "exclusions": [
        {
            "code": "EXCL-MED-NECESSITY",
            "title": "Non-Medically Necessary Treatment",
            "description": "Treatments, procedures, or diagnostic investigations that are not medically necessary.",
        },
        {
            "code": "EXCL-COSMETIC",
            "title": "Cosmetic and Aesthetic Treatment",
            "description": "Cosmetic or aesthetic procedures unless reconstructive surgery necessitated by accidental injury.",
        },
        {
            "code": "EXCL-NON-MEDICAL",
            "title": "Non-Medical Comfort Items and Consumables",
            "description": "Personal comfort items, toiletries, convenience goods, and unlisted consumables.",
        },
        {
            "code": "EXCL-HAZARDOUS",
            "title": "Hazardous Activities and Unlawful Acts",
            "description": "Injuries resulting from participation in hazardous sports, motor racing, or illegal acts.",
        },
        {
            "code": "EXCL-WAITING-PERIODS",
            "title": "Unexpired Statutory Waiting Periods",
            "description": "Expenses incurred during unexpired waiting periods (30 days initial, 36 months PED, 24 months specific conditions).",
        },
        {
            "code": "EXCL-LIMIT-EXCESS",
            "title": "Expenses Exceeding Documented Benefit Limits",
            "description": "Expenses in excess of annual sum insured or room rent and ICU daily caps.",
        },
    ],
}


MOTOR_V1_METADATA = {
    "filename": "ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf",
    "policy_identifier": "DEMO-MOTOR-SECURE-2026-V1",
    "policy_version": "1.0",
    "product_name": "Demo Motor Secure Plan",
    "insurer_name": "ClaimSage Synthetic General Insurance Ltd. (fictional)",
    "insurance_type": "auto",
    "supported_claim_types": ["auto"],
    "effective_from": date(2026, 1, 1),
    "effective_to": date(2026, 12, 31),
    "clauses": [
        {
            "page": 1,
            "index": 0,
            "identifier": "SEC-1-CONTRACT-VEHICLE",
            "category": "definition",
            "title": "Contract Preamble, Vehicle Class and Definitions",
        },
        {
            "page": 1,
            "index": 1,
            "identifier": "SEC-2-OWN-DAMAGE",
            "category": "coverage",
            "title": "Section I: Loss of or Damage to Vehicle Insured",
        },
        {
            "page": 1,
            "index": 2,
            "identifier": "SEC-3-DEDUCTIBLE-DEPRECIATION",
            "category": "limit",
            "title": "Deductibles and Scheduled Depreciation",
        },
        {
            "page": 2,
            "index": 0,
            "identifier": "SEC-4-THIRD-PARTY-EXCLUSIONS",
            "category": "exclusion",
            "title": "Section II Third-Party Liability and General Exclusions",
        },
        {
            "page": 2,
            "index": 1,
            "identifier": "SEC-5-CLAIMS-ADJUDICATION",
            "category": "condition",
            "title": "Claim Documentation, Police FIR, and Assistive AI Governance",
        },
    ],
    "coverages": [
        {
            "name": "Own Damage (Loss of or Damage to Vehicle)",
            "category": "own_damage",
            "benefit_limit": Decimal("800000.00"),
            "deductible": Decimal("1000.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": None,
            "description": (
                "Accidental external damage, fire, lightning, explosion, theft, riot, flood, or transit "
                "damage up to the verified Insured Declared Value (IDV) of INR 800,000, subject to compulsory deductible."
            ),
        },
        {
            "name": "Third-Party Liability (Bodily Injury and Death)",
            "category": "third_party_liability",
            "benefit_limit": None,
            "deductible": Decimal("0.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": None,
            "description": "Statutory legal liability for accidental death or bodily injury sustained by third parties.",
        },
        {
            "name": "Third-Party Property Damage",
            "category": "third_party_property",
            "benefit_limit": Decimal("750000.00"),
            "deductible": Decimal("0.00"),
            "co_pay_percentage": Decimal("0.00"),
            "waiting_period_days": None,
            "description": "Legal liability for third-party property damage up to statutory limit of INR 750,000.",
        },
    ],
    "exclusions": [
        {
            "code": "EXCL-WEAR-TEAR",
            "title": "Wear, Tear, and Mechanical Failure",
            "description": "Normal wear and tear, ageing, depreciation, mechanical or electrical breakdown or failures.",
        },
        {
            "code": "EXCL-UNPERMITTED-USE",
            "title": "Unpermitted Use and Commercial Carriage",
            "description": "Vehicle use outside limitations as to use, commercial hire, or carrying passengers for reward.",
        },
        {
            "code": "EXCL-UNLICENSED-DRIVER",
            "title": "Driving Without Valid Driving License",
            "description": "Vehicle driven by any person not holding an effective and valid driving license on the date of accident.",
        },
        {
            "code": "EXCL-INTOXICATION",
            "title": "Driving Under Influence of Alcohol or Drugs",
            "description": "Accident occurring whilst the driver is under the influence of intoxicating liquor or drugs.",
        },
        {
            "code": "EXCL-CONSEQUENTIAL-LOSS",
            "title": "Consequential Loss and Consumables",
            "description": "Consequential loss, unlisted consumables, and depreciation outside the specified schedule.",
        },
        {
            "code": "EXCL-WAR-NUCLEAR",
            "title": "War, Nuclear Risks, and Civil Commotion",
            "description": "Loss or damage directly or indirectly caused by war, invasion, nuclear radiation, or civil strife.",
        },
        {
            "code": "EXCL-TERRITORIAL-LIMITS",
            "title": "Losses Outside Territorial Scope",
            "description": "Losses occurring outside the geographical limits of India or outside the policy period.",
        },
    ],
}


def register_single_policy(
    session: Session,
    meta: dict,
    policy_dir: Path,
    admin_id: uuid.UUID,
) -> PolicyDocument:
    """Register and ingest a single policy PDF idempotently."""
    policy_file = policy_dir / meta["filename"]
    if not policy_file.is_file():
        raise FileNotFoundError(f"Policy file not found: {policy_file}")

    # 1. Check if policy already exists by identifier
    existing_doc = session.scalar(
        select(PolicyDocument).where(
            PolicyDocument.policy_identifier == meta["policy_identifier"]
        )
    )

    if existing_doc is not None:
        logger.info(
            "Policy %s already registered with ID %s (status: %s)",
            meta["policy_identifier"],
            existing_doc.id,
            existing_doc.status,
        )
        doc = existing_doc
    else:
        # 2. Upload file to MinIO
        storage = get_storage_service()
        storage.ensure_bucket_exists()
        storage_key = generate_secure_object_key("policies")
        with policy_file.open("rb") as f_obj:
            stored_meta = storage.upload_document(
                content=f_obj,
                object_key=storage_key,
                content_type="application/pdf",
            )
        logger.info("Uploaded %s to MinIO: %s", meta["filename"], stored_meta.object_key)

        # 3. Applicability schema
        applicability = PolicyDocumentApplicability(
            supported_claim_types=meta["supported_claim_types"],
            policy_identifier=meta["policy_identifier"],
            insurer_name=meta["insurer_name"],
            product_name=meta["product_name"],
            insurance_type=meta["insurance_type"],
            policy_version=meta["policy_version"],
            effective_from=meta["effective_from"],
            effective_to=meta["effective_to"],
        )

        # 4. Extract and persist document chunks
        doc = persist_policy_document(
            db=session,
            file_path=policy_file,
            uploader_employee_id=admin_id,
            filename=meta["filename"],
            applicability=applicability,
            source_url=None,
            storage_provider="s3",
            storage_bucket=stored_meta.bucket,
            storage_key=stored_meta.object_key,
            storage_status="stored",
        )
        doc.status = "uploaded"

        session.add(
            AuditEvent(
                actor_employee_id=admin_id,
                action="policy_document_uploaded",
                resource_type="policy_document",
                resource_id=str(doc.id),
                details=f"Policy {meta['policy_identifier']} PDF and chunks persisted.",
            )
        )
        session.commit()
        logger.info("Persisted %s with ID: %s, Chunks: %d", meta["policy_identifier"], doc.id, len(doc.chunks))

    # 5. Embed chunks if not yet processed
    if doc.status != "processed":
        logger.info("Generating embeddings for policy %s...", doc.id)
        doc = process_policy_document_embeddings(session, document_id=doc.id)
        logger.info("Embeddings complete. Policy %s status: %s", doc.id, doc.status)

    # 6. Retrieve chunks for clause mapping
    chunks = session.scalars(
        select(PolicyChunk)
        .where(PolicyChunk.document_id == doc.id)
        .order_by(PolicyChunk.page_number, PolicyChunk.chunk_index)
    ).all()
    chunk_map = {(c.page_number, c.chunk_index): c for c in chunks}
    now_utc = datetime.now(timezone.utc)

    # 7. Seed PolicyClauses
    for cdef in meta["clauses"]:
        chunk = chunk_map.get((cdef["page"], cdef["index"]))
        if not chunk:
            logger.warning("Chunk (%d, %d) not found for clause %s", cdef["page"], cdef["index"], cdef["identifier"])
            continue

        existing_clause = session.scalar(
            select(PolicyClause).where(PolicyClause.source_chunk_id == chunk.id)
        )
        if existing_clause:
            continue

        clause = PolicyClause(
            id=uuid.uuid4(),
            document_id=doc.id,
            source_chunk_id=chunk.id,
            clause_identifier=cdef["identifier"],
            clause_category=cdef["category"],
            title=cdef["title"],
            clause_text=chunk.text,
            source_page_number=cdef["page"],
            verification_status="verified",
            verified_by_employee_id=admin_id,
            verified_at=now_utc,
        )
        session.add(clause)

    # 8. Seed PolicyCoverages
    for cov in meta["coverages"]:
        existing_cov = session.scalar(
            select(PolicyCoverage).where(
                PolicyCoverage.document_id == doc.id,
                PolicyCoverage.coverage_name == cov["name"],
            )
        )
        if existing_cov:
            continue

        coverage = PolicyCoverage(
            id=uuid.uuid4(),
            document_id=doc.id,
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

    # 9. Seed PolicyExclusions
    for excl in meta["exclusions"]:
        existing_excl = session.scalar(
            select(PolicyExclusion).where(
                PolicyExclusion.document_id == doc.id,
                PolicyExclusion.exclusion_code == excl["code"],
            )
        )
        if existing_excl:
            continue

        exclusion = PolicyExclusion(
            id=uuid.uuid4(),
            document_id=doc.id,
            exclusion_code=excl["code"],
            title=excl["title"],
            description=excl["description"],
        )
        session.add(exclusion)

    session.commit()
    logger.info("Successfully configured structured knowledge for policy %s", meta["policy_identifier"])
    return doc


def main() -> None:
    policy_dir = Path("/app/docs/policies") if Path("/app/docs/policies").is_dir() else Path("docs/policies")

    with SessionLocal() as session:
        admin = session.scalar(
            select(Employee).where(Employee.email == "admin@claimsage.local")
        )
        if not admin:
            raise RuntimeError("Admin employee 'admin@claimsage.local' not found!")
        admin_id = admin.id

        logger.info("=== Registering Health v3 Policy ===")
        health_doc = register_single_policy(session, HEALTH_V3_METADATA, policy_dir, admin_id)

        logger.info("=== Registering Motor v1 Policy ===")
        motor_doc = register_single_policy(session, MOTOR_V1_METADATA, policy_dir, admin_id)

        logger.info("=== Policy Registration Finished ===")
        logger.info("Health v3: ID=%s, status=%s", health_doc.id, health_doc.status)
        logger.info("Motor v1:  ID=%s, status=%s", motor_doc.id, motor_doc.status)


if __name__ == "__main__":
    main()
