"""Insert isolated synthetic Motor and Health investigation scenarios."""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import TypeGuard
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

import pymupdf
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    PolicyDocument,
)
from claimsage.db.models import (
    PolicyDocumentApplicability as PolicyApplicabilityModel,
)
from claimsage.demo_scenarios import (
    HEALTH_SCENARIO,
    DemoScenario,
    EvidenceFixture,
)
from claimsage.rag.document_loader import MAX_PDF_SIZE_BYTES
from claimsage.schemas.policies import PolicyDocumentApplicability
from claimsage.services.document_persistence import persist_policy_document
from claimsage.services.embedding_persistence import embed_pending_policy_chunks
from claimsage.services.evidence_persistence import persist_claim_evidence
from claimsage.services.notifications import (
    NotificationEvent,
    dispatch_notification,
    enqueue_notification,
)

SCENARIOS_TO_SEED = (HEALTH_SCENARIO,)
ALLOWED_SOURCE_HOSTS = {"newindia.co.in", "www.newindia.co.in"}
logger = logging.getLogger(__name__)


def _test_database_url() -> str:
    """Require an explicit process URL for the isolated PostgreSQL test DB."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "Set DATABASE_URL explicitly to the PostgreSQL claimsage_test database."
        )

    try:
        parsed_url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise RuntimeError(
            "DATABASE_URL must be a valid PostgreSQL URL for claimsage_test."
        ) from None

    if (
        parsed_url.get_backend_name() != "postgresql"
        or parsed_url.database != "claimsage_test"
    ):
        raise RuntimeError(
            "Refusing to seed: DATABASE_URL must target PostgreSQL claimsage_test."
        )

    return database_url


def _verify_connected_database(connection: Connection) -> None:
    """Confirm the server-side database name before any write is attempted."""
    try:
        database_name = connection.scalar(text("SELECT current_database()"))
    except SQLAlchemyError:
        raise RuntimeError(
            "Could not verify the PostgreSQL test database connection."
        ) from None

    if database_name != "claimsage_test":
        raise RuntimeError(
            "Refusing to seed: connected database is not claimsage_test."
        )


def _download_official_policy(source_url: str, destination: Path) -> None:
    """Download a bounded PDF from the fixed official New India host."""
    request = Request(
        source_url,
        headers={"User-Agent": "ClaimSage synthetic demo seed"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            final_host = urlsplit(response.geturl()).hostname
            if (
                response.status != 200
                or final_host not in ALLOWED_SOURCE_HOSTS
            ):
                raise RuntimeError(
                    "The official policy source did not return an accepted response."
                )
            content = response.read(MAX_PDF_SIZE_BYTES + 1)
    except OSError as exc:
        raise RuntimeError(
            "The official policy PDF could not be downloaded."
        ) from exc

    if len(content) > MAX_PDF_SIZE_BYTES or not content.startswith(b"%PDF-"):
        raise RuntimeError(
            "The official policy source is not a supported PDF within the size limit."
        )

    destination.write_bytes(content)


def _write_synthetic_evidence(
    evidence: EvidenceFixture,
    destination: Path,
) -> None:
    """Render a clearly synthetic fixture to a temporary one-page PDF."""
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((48, 42), evidence.title, fontsize=14)
        remaining = page.insert_textbox(
            pymupdf.Rect(48, 65, 547, 790),
            evidence.text,
            fontsize=10,
            lineheight=1.25,
        )
        if remaining < 0:
            raise RuntimeError(
                f"Synthetic fixture {evidence.filename} exceeds one page."
            )
        document.save(destination)
    finally:
        document.close()


def _prepare_documents(
    temporary_directory: Path,
) -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    policy_paths: dict[str, Path] = {}
    evidence_paths: dict[tuple[str, str], Path] = {}

    for scenario in SCENARIOS_TO_SEED:
        policy_path = temporary_directory / (
            f"{scenario.claim_type}_official_policy.pdf"
        )
        _download_official_policy(scenario.policy.source_url, policy_path)
        policy_paths[scenario.claim_type] = policy_path

        for evidence in scenario.evidence:
            evidence_path = temporary_directory / evidence.filename
            _write_synthetic_evidence(evidence, evidence_path)
            evidence_paths[(scenario.claim_type, evidence.filename)] = (
                evidence_path
            )

    return policy_paths, evidence_paths


def _existing_claims(session: Session) -> dict[str, Claim]:
    claims = session.scalars(
        select(Claim).where(
            Claim.claim_number.in_(
                [scenario.claim_number for scenario in SCENARIOS_TO_SEED]
            )
        )
    ).all()
    return {claim.claim_number: claim for claim in claims}


def _can_seed_as(employee: Employee | None) -> TypeGuard[Employee]:
    return employee is not None and (
        employee.role == EmployeeRole.ADMIN
        or (
            employee.role == EmployeeRole.POLICY_SPECIALIST
            and employee.team_id is not None
        )
    )


def _seed_policy(
    session: Session,
    *,
    scenario: DemoScenario,
    policy_path: Path,
    employee_id: UUID,
) -> PolicyDocument:
    fixture = scenario.policy
    applicability = None
    if fixture.effective_from is not None:
        applicability = PolicyDocumentApplicability(
            supported_claim_types=[scenario.claim_type],
            policy_identifier=fixture.policy_identifier,
            insurer_name=fixture.insurer_name,
            product_name=fixture.product_name,
            insurance_type=fixture.insurance_type,
            policy_version=fixture.policy_version,
            effective_from=fixture.effective_from,
            effective_to=fixture.effective_to,
        )

    document = persist_policy_document(
        db=session,
        file_path=policy_path,
        uploader_employee_id=employee_id,
        filename=policy_path.name,
        applicability=applicability,
        source_url=fixture.source_url,
    )

    if applicability is None:
        document.policy_identifier = fixture.policy_identifier
        document.insurer_name = fixture.insurer_name
        document.product_name = fixture.product_name
        document.insurance_type = fixture.insurance_type
        document.policy_version = fixture.policy_version
        session.add(
            PolicyApplicabilityModel(
                document_id=document.id,
                claim_type=scenario.claim_type,
            )
        )

    while embed_pending_policy_chunks(
        session,
        document_id=document.id,
    ):
        pass

    return document


def _seed_scenario(
    session: Session,
    *,
    scenario: DemoScenario,
    policy_path: Path,
    evidence_paths: dict[tuple[str, str], Path],
    employee: Employee,
) -> tuple[Claim, dict[str, str]]:
    claim = Claim(
        claim_number=scenario.claim_number,
        claimant_name=scenario.claimant_name,
        claim_type=scenario.claim_type,
        status="under_review",
        assigned_employee_id=employee.id,
        policy_identifier=scenario.policy.policy_identifier,
        insurer_name=scenario.policy.insurer_name,
        product_name=scenario.policy.product_name,
        loss_date=scenario.loss_date,
        team_id=employee.team_id,
        summary=scenario.summary,
    )
    session.add(claim)
    session.flush()

    _seed_policy(
        session,
        scenario=scenario,
        policy_path=policy_path,
        employee_id=employee.id,
    )

    document_ids: dict[str, str] = {}
    for evidence in scenario.evidence:
        document = persist_claim_evidence(
            db=session,
            file_path=evidence_paths[
                (scenario.claim_type, evidence.filename)
            ],
            claim_id=claim.id,
            uploader_employee_id=employee.id,
            filename=evidence.filename,
        )
        document_ids[evidence.filename] = str(document.id)

    return claim, document_ids


def seed_investigation_scenarios(employee_email: str) -> None:
    """Add the synthetic Health claim without changing existing demo records."""
    os.environ["CLAIMSAGE_DISABLE_DOTENV"] = "1"
    database_url = _test_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            _verify_connected_database(connection)
            with Session(bind=connection) as session:
                existing = _existing_claims(session)
                if HEALTH_SCENARIO.claim_number in existing:
                    print(
                        f"Health synthetic claim "
                        f"{HEALTH_SCENARIO.claim_number} already exists; "
                        "no records were changed."
                    )
                    return

                employee = session.scalar(
                    select(Employee).where(Employee.email == employee_email)
                )
                if not _can_seed_as(employee):
                    raise RuntimeError(
                        "Provide an existing claimsage_test administrator or "
                        "team policy specialist; no employee will be changed."
                    )

        with tempfile.TemporaryDirectory(
            prefix="claimsage-scenarios-"
        ) as directory:
            temporary_directory = Path(directory)
            policy_paths, evidence_paths = _prepare_documents(
                temporary_directory
            )
            scenario_results: dict[str, tuple[Claim, dict[str, str]]] = {}

            with engine.begin() as connection:
                _verify_connected_database(connection)
                with Session(
                    bind=connection,
                    autoflush=False,
                    expire_on_commit=False,
                ) as session:
                    with session.begin():
                        existing = _existing_claims(session)
                        if existing:
                            raise RuntimeError(
                                "The Health synthetic claim appeared during "
                                "seeding; refusing to alter it."
                            )

                        employee = session.scalar(
                            select(Employee).where(
                                Employee.email == employee_email
                            )
                        )
                        if not _can_seed_as(employee):
                            raise RuntimeError(
                                "The selected test policy operator is unavailable."
                            )

                        for scenario in SCENARIOS_TO_SEED:
                            scenario_results[scenario.claim_type] = (
                                _seed_scenario(
                                    session,
                                    scenario=scenario,
                                    policy_path=policy_paths[
                                        scenario.claim_type
                                    ],
                                    evidence_paths=evidence_paths,
                                    employee=employee,
                                )
                            )

                        session.add(
                            AuditEvent(
                                actor_employee_id=employee.id,
                                action="synthetic_health_scenario_seeded",
                                resource_type="demo_dataset",
                                resource_id=HEALTH_SCENARIO.claim_number,
                                details=(
                                    "Inserted the synthetic Health "
                                    "investigation scenario."
                                ),
                            )
                        )

        for scenario in SCENARIOS_TO_SEED:
            claim, document_ids = scenario_results[scenario.claim_type]
            print(
                f"health: {scenario.claim_number} "
                f"(claim_id={claim.id})"
            )
            for filename, document_id in document_ids.items():
                print(f"{filename} (document_id={document_id})")
            try:
                recipient_employee_id = claim.assigned_employee_id
                if recipient_employee_id is None:
                    raise RuntimeError(
                        "The seeded claim has no assigned notification recipient."
                    )
                with Session(engine) as notification_session:
                    notification_id = enqueue_notification(
                        notification_session,
                        event=NotificationEvent.CLAIM_RECEIVED,
                        recipient_employee_id=recipient_employee_id,
                        resource_id=claim.id,
                        application_path=f"/claims/{claim.id}",
                    )
                    notification_session.commit()
                dispatch_notification(
                    notification_id,
                    session_factory=lambda: Session(engine),
                )
            except Exception as exc:
                logger.warning(
                    "Claim receipt notification failed (error_type=%s).",
                    type(exc).__name__,
                )
        print("No policy clauses were auto-verified; human review is required.")
    except SQLAlchemyError:
        raise RuntimeError(
            "Scenario seeding failed; the database transaction was rolled back."
        ) from None
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--employee-email",
        required=True,
        help=(
            "Email of an existing claimsage_test administrator or team "
            "policy specialist who will be assigned to the Health claim."
        ),
    )
    arguments = parser.parse_args()
    employee_email = arguments.employee_email.strip().casefold()
    if "@" not in employee_email:
        parser.error("--employee-email must be a valid email address.")
    seed_investigation_scenarios(employee_email)


if __name__ == "__main__":
    main()
