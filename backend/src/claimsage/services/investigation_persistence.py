"""Persistence helpers for durable investigation execution state."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from claimsage.db.models import (
    AuditEvent,
    Claim,
    ClaimEvidenceChunk,
    InvestigationFinding,
    InvestigationFindingReference,
    InvestigationReport,
    InvestigationRun,
    PolicyChunk,
    PolicyClause,
)

_FINDING_FIELDS = (
    "summary",
    "factual_findings",
    "timeline",
    "inconsistencies",
    "relevant_clauses",
    "summary_quotes",
    "assessment_quotes",
    "coverage_indicators",
    "exclusions_and_conditions",
    "missing_information",
    "evidence_gaps",
    "extracted_fields",
    "document_flags",
    "document_inventory",
    "findings",
    "clarification_needs",
    "observed_facts",
    "anomalies",
    "hypotheses",
    "conflicting_findings",
    "analyst_interpretations",
)

_SPECIALISTS = (
    "intake_analysis",
    "evidence_analysis",
    "policy_analysis",
    "repair_estimate_analysis",
    "risk_analysis",
    "review_report",
)


def normalize_claim_domain(claim_type: str) -> str:
    """Map the current motor taxonomy and Health domain to stable run values."""
    normalized = claim_type.strip().lower()
    if normalized in {"auto", "motor"}:
        return "auto"
    if normalized == "health":
        return "health"
    return "other"


def create_investigation_run(
    session: Session,
    *,
    claim: Claim,
    employee_id: UUID,
    task: str,
    repair_estimate_document_id: UUID | None = None,
    max_attempts: int = 3,
) -> InvestigationRun:
    """Commit a durable queued investigation job record before any worker execution."""
    domain = normalize_claim_domain(claim.claim_type)
    investigation = InvestigationRun(
        id=uuid4(),
        claim_id=claim.id,
        claim_domain=domain,
        initiated_by_employee_id=employee_id,
        task=task,
        status="running",
        current_stage="queued",
        state_snapshot=(
            {"repair_estimate_document_id": str(repair_estimate_document_id)}
            if repair_estimate_document_id is not None
            else {}
        ),
        attempt_count=0,
        max_attempts=max_attempts,
        repair_estimate_document_id=repair_estimate_document_id,
    )
    session.add(investigation)
    session.flush()
    session.add(
        AuditEvent(
            actor_type="employee",
            actor_employee_id=employee_id,
            claim_id=claim.id,
            investigation_id=investigation.id,
            event_category="investigation",
            action="investigation_started",
            outcome="success",
            resource_type="investigation",
            resource_id=str(investigation.id),
            details="Investigation execution started.",
            event_metadata={
                "task": task[:500],
                "claim_domain": domain,
            },
        )
    )
    session.commit()
    session.refresh(investigation)
    return investigation


def persist_progress(
    session: Session,
    *,
    investigation: InvestigationRun,
    stage: str,
    state: Mapping[str, Any],
    lease_seconds: int = 120,
) -> None:
    """Persist each graph update, its source-preserving findings, and update lease heartbeat."""
    investigation.current_stage = stage
    investigation.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    investigation.state_snapshot = _serialize_state(state)
    _replace_findings(session, investigation, state)
    _sync_report(session, investigation, state)
    session.commit()

def is_investigation_complete(state: Mapping[str, Any]) -> bool:
    """Keep terminal status incomplete when a report or required agent failed."""

    if state.get("error"):
        return False
    result = state.get("result")
    if not isinstance(result, dict):
        return False
    if (
        result.get("review_report_status") != "completed"
        or result.get("provider_failures")
    ):
        return False

    report = result.get("review_report")
    if (
        not isinstance(report, dict)
        or report.get("overall_status")
        not in {"completed", "insufficient_evidence"}
    ):
        return False
    coverage = report.get("specialist_coverage")
    if not isinstance(coverage, list) or any(
        isinstance(specialist, dict)
        and specialist.get("status") in {"unavailable", "failed", "pending"}
        for specialist in coverage
    ):
        return False
    return True



def finish_investigation(
    session: Session,
    *,
    investigation: InvestigationRun,
    state: Mapping[str, Any],
) -> None:
    """Persist final state, report status, and terminal run status."""
    snapshot = _serialize_state(state)
    investigation.state_snapshot = snapshot
    investigation.current_stage = None
    investigation.worker_id = None
    investigation.lease_expires_at = None
    investigation.completed_at = datetime.now(UTC)
    if state.get("error"):
        investigation.status = "failed"
        investigation.failure_type = "InvestigationWorkflowError"
    elif is_investigation_complete(state):
        investigation.status = "completed"
    else:
        investigation.status = "incomplete"
    _replace_findings(session, investigation, state)
    _sync_report(session, investigation, state)
    action_name = (
        "investigation_failed"
        if getattr(investigation, "status", None) == "failed"
        else "investigation_finished"
    )
    inv_id = getattr(investigation, "id", None)
    existing_audit = None
    if inv_id is not None:
        try:
            candidate = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.investigation_id == inv_id,
                    AuditEvent.action == action_name,
                )
            )
            if isinstance(candidate, AuditEvent):
                existing_audit = candidate
        except Exception:
            existing_audit = None

    if existing_audit is not None:
        existing_audit.outcome = (
            "failure" if getattr(investigation, "status", None) == "failed" else "success"
        )
        existing_audit.details = (
            f"Investigation ended with status {getattr(investigation, 'status', None)}."
        )
        existing_audit.event_metadata = {
            "status": getattr(investigation, "status", None),
            "failure_type": getattr(investigation, "failure_type", None),
        }
    else:
        session.add(
            AuditEvent(
                actor_type="employee",
                actor_employee_id=getattr(investigation, "initiated_by_employee_id", None),
                claim_id=getattr(investigation, "claim_id", None),
                investigation_id=inv_id,
                event_category="investigation",
                action=action_name,
                outcome="failure" if getattr(investigation, "status", None) == "failed" else "success",
                resource_type="investigation",
                resource_id=str(inv_id),
                details=f"Investigation ended with status {getattr(investigation, 'status', None)}.",
                event_metadata={
                    "status": getattr(investigation, "status", None),
                    "failure_type": getattr(investigation, "failure_type", None),
                },
            )
        )
    session.commit()


def fail_investigation(
    session: Session,
    *,
    investigation: InvestigationRun,
    failure_type: str,
    state: Mapping[str, Any] | None = None,
) -> None:
    """Record a sanitized exception category without storing exception text."""
    session.rollback()
    investigation.status = "failed"
    investigation.current_stage = None
    investigation.worker_id = None
    investigation.lease_expires_at = None
    investigation.failure_type = failure_type[:200]
    investigation.completed_at = datetime.now(UTC)
    if state is not None:
        investigation.state_snapshot = _serialize_state(state)
        _replace_findings(session, investigation, state)
        _sync_report(session, investigation, state)
    session.add(
        AuditEvent(
            actor_employee_id=investigation.initiated_by_employee_id,
            action="investigation_failed",
            resource_type="investigation",
            resource_id=str(investigation.id),
            details="Investigation execution failed.",
        )
    )
    session.commit()


def _serialize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Convert graph values to JSON-compatible data and omit trusted identity."""
    return {
        key: _to_json_value(value)
        for key, value in state.items()
        if key != "employee_id"
    }


def _to_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    return value


def _replace_findings(
    session: Session,
    investigation: InvestigationRun,
    state: Mapping[str, Any],
) -> None:
    session.execute(
        delete(InvestigationFinding).where(
            InvestigationFinding.investigation_id == investigation.id
        )
    )

    retrieved = _retrieved_sources(state)
    rows: list[InvestigationFinding] = []
    for specialist_key in _SPECIALISTS:
        output = state.get(specialist_key)
        if specialist_key == "review_report" and output is None:
            res_dict = state.get("result")
            if isinstance(res_dict, Mapping):
                output = res_dict.get("fallback_report")
        output_data = _to_json_value(output)
        if not isinstance(output_data, dict):
            continue
        specialist = specialist_key.removesuffix("_analysis")
        if specialist_key == "review_report":
            specialist = "review_report"
        for field in _FINDING_FIELDS:
            value = output_data.get(field)
            if isinstance(value, list):
                for index, item in enumerate(value):
                    finding_data = (
                        item if isinstance(item, dict) else {"value": item}
                    )
                    rows.append(
                        _make_finding(
                            investigation_id=investigation.id,
                            specialist=specialist,
                            finding_type=f"{field}[{index}]",
                            data=finding_data,
                            retrieved=retrieved,
                        )
                    )
            elif isinstance(value, str) and value.strip():
                rows.append(
                    _make_finding(
                        investigation_id=investigation.id,
                        specialist=specialist,
                        finding_type=field,
                        data={"value": value},
                        retrieved=retrieved,
                    )
                )

    session.add_all(rows)
    session.flush()
    _add_relational_references(session, rows, retrieved)


def _make_finding(
    *,
    investigation_id: UUID,
    specialist: str,
    finding_type: str,
    data: dict[str, Any],
    retrieved: dict[str, dict[str, Any]],
) -> InvestigationFinding:
    reference_ids = _reference_ids(data)
    evidence_references: list[dict[str, Any]] = []
    policy_references: list[dict[str, Any]] = []
    for source_id in reference_ids:
        source = retrieved.get(source_id)
        reference = {
            "source_id": source_id,
            "resolved_from_retrieval": source is not None,
            "provenance": source or {},
        }
        if source is not None and source.get("source_kind") == "policy_chunk":
            policy_references.append(reference)
        else:
            evidence_references.append(reference)

    clause_ids = _clause_reference_ids(data)
    for source_id in clause_ids:
        policy_references.append(
            {
                "source_id": source_id,
                "source_kind": "policy_clause",
                "resolved_from_retrieval": any(
                    source.get("clause_id") == source_id
                    for source in retrieved.values()
                ),
            }
        )

    return InvestigationFinding(
        id=uuid4(),
        investigation_id=investigation_id,
        specialist=specialist,
        finding_type=finding_type,
        finding_data=_to_json_value(data),
        severity=_allowed_value(data.get("severity"), {"low", "medium", "high"}),
        confidence=_allowed_value(
            data.get("confidence"),
            {"low", "medium", "high"},
        ),
        evidence_references=evidence_references,
        policy_references=policy_references,
    )


def _retrieved_sources(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    source_lists = (
        ("claim_evidence", "claim_evidence"),
        ("repair_estimate_evidence", "claim_evidence"),
        ("policy_evidence", "policy_chunk"),
    )
    for field, source_kind in source_lists:
        chunks = state.get(field)
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            serialized_chunk = _to_json_value(chunk)
            chunk_id = chunk.get("chunk_id")
            if isinstance(chunk_id, str):
                sources[chunk_id] = {
                    **serialized_chunk,
                    "source_kind": source_kind,
                }
            clause_id = chunk.get("clause_id")
            if (
                source_kind == "policy_chunk"
                and isinstance(clause_id, str)
                and clause_id not in sources
            ):
                sources[clause_id] = {
                    **serialized_chunk,
                    "source_kind": "policy_clause",
                }
    return sources


def _reference_ids(value: Any) -> set[str]:
    reference_ids: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"supporting_evidence_ids", "source_evidence_ids"}:
                if isinstance(nested, list):
                    reference_ids.update(
                        item for item in nested if isinstance(item, str)
                    )
            elif key in {"evidence_id", "chunk_id"} and isinstance(nested, str):
                reference_ids.add(nested)
            else:
                reference_ids.update(_reference_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            reference_ids.update(_reference_ids(nested))
    return reference_ids


def _clause_reference_ids(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "clause_id" and isinstance(nested, str):
                ids.add(nested)
            else:
                ids.update(_clause_reference_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            ids.update(_clause_reference_ids(nested))
    return ids


def _add_relational_references(
    session: Session,
    findings: list[InvestigationFinding],
    retrieved: dict[str, dict[str, Any]],
) -> None:
    source_ids = {
        source_id
        for finding in findings
        for source_id in (
            _reference_ids(finding.finding_data)
            | _clause_reference_ids(finding.finding_data)
        )
    }
    if not source_ids:
        return

    source_uuids: set[UUID] = set()
    for source_id in source_ids:
        try:
            source_uuids.add(UUID(source_id))
        except ValueError:
            continue

    claim_chunk_filters = [ClaimEvidenceChunk.chunk_id.in_(source_ids)]
    if source_uuids:
        claim_chunk_filters.append(ClaimEvidenceChunk.id.in_(source_uuids))

    claim_chunks: dict[str, UUID] = {}
    for chunk in session.scalars(
        select(ClaimEvidenceChunk).where(or_(*claim_chunk_filters))
    ):
        if getattr(chunk, "chunk_id", None):
            claim_chunks[chunk.chunk_id] = chunk.id
        if getattr(chunk, "id", None) is not None:
            claim_chunks[str(chunk.id)] = chunk.id

    policy_chunk_filters = [PolicyChunk.chunk_id.in_(source_ids)]
    if source_uuids:
        policy_chunk_filters.append(PolicyChunk.id.in_(source_uuids))

    policy_chunks: dict[str, UUID] = {}
    for chunk in session.scalars(
        select(PolicyChunk).where(or_(*policy_chunk_filters))
    ):
        if getattr(chunk, "chunk_id", None):
            policy_chunks[chunk.chunk_id] = chunk.id
        if getattr(chunk, "id", None) is not None:
            policy_chunks[str(chunk.id)] = chunk.id

    clause_ids: dict[str, UUID] = {}
    for source_id in source_ids:
        try:
            clause_uuid = UUID(source_id)
        except ValueError:
            continue
        clause = session.get(PolicyClause, clause_uuid)
        if clause is not None:
            clause_ids[source_id] = clause.id

    references: list[InvestigationFindingReference] = []
    for finding in findings:
        for source_id in (
            _reference_ids(finding.finding_data)
            | _clause_reference_ids(finding.finding_data)
        ):
            source = retrieved.get(source_id, {})
            claim_chunk_id = claim_chunks.get(source_id)
            policy_chunk_id = policy_chunks.get(source_id)
            clause_id = clause_ids.get(source_id)
            if claim_chunk_id is not None:
                source_kind = "claim_evidence"
                policy_chunk_id = None
                clause_id = None
            elif policy_chunk_id is not None:
                source_kind = "policy_chunk"
                clause_id = None
            elif clause_id is not None:
                source_kind = "policy_clause"
            else:
                source_kind = "unresolved"
            references.append(
                InvestigationFindingReference(
                    finding_id=finding.id,
                    source_kind=source_kind,
                    source_id=source_id,
                    claim_evidence_chunk_id=claim_chunk_id,
                    policy_chunk_id=policy_chunk_id,
                    policy_clause_id=clause_id,
                    provenance=source,
                )
            )
    session.add_all(references)


def _sync_report(
    session: Session,
    investigation: InvestigationRun,
    state: Mapping[str, Any],
) -> None:
    report_status = state.get("review_report_status")
    if report_status in {None, "pending"}:
        return
    mapped_status = {
        "completed": "completed",
        "incomplete": "incomplete",
        "unavailable": "unavailable",
        "failed": "unavailable",
        "skipped": "skipped",
    }.get(str(report_status), "unavailable")

    report_output = _to_json_value(state.get("review_report"))
    if not isinstance(report_output, dict):
        report_output = None
    result = state.get("result")
    if report_output is None and isinstance(result, Mapping):
        fallback_output = _to_json_value(result.get("fallback_report"))
        if isinstance(fallback_output, dict):
            report_output = fallback_output
            if mapped_status == "unavailable":
                mapped_status = "incomplete"
    limitations = (
        result.get("limitations", [])
        if isinstance(result, Mapping)
        else []
    )
    if not isinstance(limitations, list):
        limitations = []

    report = session.scalar(
        select(InvestigationReport).where(
            InvestigationReport.investigation_id == investigation.id
        )
    )
    if report is None:
        report = InvestigationReport(
            investigation_id=investigation.id,
            status=mapped_status,
            report_data=report_output,
            limitations=_to_json_value(limitations),
            human_review_required=True,
        )
        session.add(report)
    else:
        report.status = mapped_status
        report.report_data = report_output
        report.limitations = _to_json_value(limitations)
        report.human_review_required = True


def _allowed_value(value: Any, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None
