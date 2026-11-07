"""Database-free checks for investigation serialization and domain handling."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from claimsage.schemas.investigation import InvestigationReviewRequest
from claimsage.services import investigation_persistence
from claimsage.services.investigation_persistence import (
    _make_finding,
    _serialize_state,
    finish_investigation,
    is_investigation_complete,
    normalize_claim_domain,
    persist_progress,
)


def test_motor_and_health_domains_share_stable_values() -> None:
    assert normalize_claim_domain("auto") == "auto"
    assert normalize_claim_domain("motor") == "auto"
    assert normalize_claim_domain("health") == "health"
    assert normalize_claim_domain("property") == "other"


def test_state_snapshot_omits_trusted_employee_identity() -> None:
    employee_id = uuid4()
    claim_id = uuid4()

    snapshot = _serialize_state(
        {
            "employee_id": str(employee_id),
            "claim_id": str(claim_id),
            "result": {"human_review_required": True},
        }
    )

    assert "employee_id" not in snapshot
    assert snapshot["claim_id"] == str(claim_id)


def test_progress_and_terminal_state_persist_partial_ai_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    investigation = SimpleNamespace(
        id=uuid4(),
        initiated_by_employee_id=uuid4(),
        current_stage=None,
        state_snapshot={},
        status="running",
        failure_type=None,
        completed_at=None,
    )
    monkeypatch.setattr(
        investigation_persistence,
        "_replace_findings",
        MagicMock(),
    )
    monkeypatch.setattr(
        investigation_persistence,
        "_sync_report",
        MagicMock(),
    )
    state = {
        "employee_id": str(uuid4()),
        "claim_id": str(uuid4()),
        "result": {
            "human_review_required": True,
            "provider_failures": [
                {
                    "stage": "policy_analysis",
                    "category": "rate_limited",
                    "status_code": 429,
                }
            ],
        },
        "review_report_status": "unavailable",
    }

    persist_progress(
        session,
        investigation=investigation,
        stage="policy_analyst",
        state=state,
    )
    finish_investigation(
        session,
        investigation=investigation,
        state=state,
    )

    assert investigation.current_stage is None
    assert investigation.status == "incomplete"
    assert investigation.state_snapshot["result"]["human_review_required"] is True
    assert investigation.state_snapshot["result"]["provider_failures"] == [
        {
            "stage": "policy_analysis",
            "category": "rate_limited",
            "status_code": 429,
        }
    ]
    assert "employee_id" not in investigation.state_snapshot
    assert session.commit.call_count == 2


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "insufficient_evidence",
                    "specialist_coverage": [],
                },
            },
            True,
        ),
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "completed",
                    "specialist_coverage": [
                        {"status": "unavailable"}
                    ],
                },
            },
            False,
        ),
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "completed",
                    "specialist_coverage": [],
                },
                "provider_failures": [{"stage": "policy_analyst"}],
            },
            False,
        ),
        (
            {
                "review_report_status": "unavailable",
                "review_report": None,
            },
            False,
        ),
    ],
)
def test_terminal_execution_status_reflects_required_agent_failures(
    result: dict[str, object],
    expected: bool,
) -> None:
    assert is_investigation_complete({"result": result}) is expected


def test_finding_keeps_exact_source_reference_and_resolution_status() -> None:
    evidence_id = "claim-chunk-123"

    finding = _make_finding(
        investigation_id=uuid4(),
        specialist="evidence",
        finding_type="factual_findings[0]",
        data={
            "finding": "A source-backed synthetic finding.",
            "supporting_evidence_ids": [evidence_id],
            "confidence": "medium",
        },
        retrieved={
            evidence_id: {
                "chunk_id": evidence_id,
                "document_id": "doc-1",
                "page_number": 2,
                "source_kind": "claim_evidence",
            }
        },
    )

    assert finding.evidence_references[0]["source_id"] == evidence_id
    assert finding.evidence_references[0]["resolved_from_retrieval"] is True
    assert finding.confidence == "medium"


@pytest.mark.parametrize(
    "decision",
    ["approve", "deny", "reject", "settle", "pay"],
)
def test_review_request_rejects_claim_disposition_decisions(
    decision: str,
) -> None:
    with pytest.raises(ValidationError):
        InvestigationReviewRequest.model_validate({"decision": decision})
