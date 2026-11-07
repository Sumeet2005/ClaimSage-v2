"""Mocked graph integration tests for Risk & Anomaly Agent routing."""

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents.graph import run_investigation
from claimsage.agents.risk_anomaly_agent import RiskAnomalyAgentError
from claimsage.agents.schemas import (
    RepairEstimateAnalystOutput,
    ReviewReportOutput,
    RiskAnomalyEvidenceQuote,
    RiskAnomalyFinding,
    RiskAnomalyOutput,
    RiskAnomalySourceReference,
    SupervisorPlan,
)
from claimsage.rag.evidence_retrieval_service import (
    EvidenceRetrievalError,
    RetrievedEvidenceChunk,
)


def make_session() -> Session:
    """Create an isolated mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture(autouse=True)
def mock_review_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            return_value=ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="not_performed",
                evidence_scope_note="Synthetic report for risk tests.",
                human_review_required=True,
            )
        ),
    )


def make_facts(claim_id):
    """Create synthetic authorized structured claim facts."""
    return {
        "claim_id": str(claim_id),
        "claim_number": "CLM-RISK-001",
        "claim_type": "property",
        "policy_identifier": "TEST-PROPERTY-POLICY",
        "loss_date": "2026-04-02",
        "status": "under_review",
    }


def make_chunk(*, filename, text, page_number=1):
    """Create retrieved UUID-backed provenance data."""
    return RetrievedEvidenceChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=filename,
        page_number=page_number,
        chunk_index=0,
        text=text,
        similarity=0.9,
        embedding_model="synthetic-model",
        extraction_method="native",
        ocr_confidence=None,
    )


def make_dict_chunk(chunk):
    """Match the graph's serialized retrieved evidence shape."""
    return {
        "chunk_id": str(chunk.chunk_id),
        "document_id": str(chunk.document_id),
        "filename": chunk.filename,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "similarity": chunk.similarity,
        "embedding_model": chunk.embedding_model,
        "extraction_method": chunk.extraction_method,
        "ocr_confidence": chunk.ocr_confidence,
    }


def setup_plan(monkeypatch, selected_analysts):
    """Mock the validated plan and authorized claim retrieval."""
    employee_id = uuid4()
    claim_id = uuid4()
    facts = make_facts(claim_id)
    supervisor = MagicMock(
        return_value=SupervisorPlan(
            selected_analysts=selected_analysts,
            routing_rationale="Synthetic risk integration test.",
            human_review_required=True,
        )
    )
    monkeypatch.setattr(graph_module, "create_supervisor_plan", supervisor)
    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    return employee_id, claim_id, facts, supervisor


def model_result(payload):
    """Create an analyst response with a deterministic JSON serialization."""
    result = MagicMock()
    result.model_dump.return_value = payload
    return result


def make_risk_output(chunk):
    """Create a valid source-provenanced synthetic risk output."""
    evidence_id = str(chunk.chunk_id)
    return RiskAnomalyOutput(
        overall_status="analyzed",
        anomalies=[
            RiskAnomalyFinding(
                finding="Potential inconsistency: source dates differ.",
                explanation="The cited claim record states April 2, 2026.",
                supporting_evidence_ids=[evidence_id],
                supporting_quotes=[
                    RiskAnomalyEvidenceQuote(
                        evidence_id=evidence_id,
                        quote=chunk.text,
                    )
                ],
                sources=[
                    RiskAnomalySourceReference(
                        evidence_id=evidence_id,
                        document_id=str(chunk.document_id),
                        filename=chunk.filename,
                        page_number=chunk.page_number,
                    )
                ],
            )
        ],
        human_review_required=True,
    )


def test_selected_risk_agent_runs_last_with_completed_upstream_context(
    monkeypatch,
):
    """Risk analysis receives trusted facts, evidence, and completed outputs."""
    employee_id, claim_id, facts, supervisor = setup_plan(
        monkeypatch,
        [
            "intake_agent",
            "evidence_analyst",
            "policy_analyst",
            "repair_estimate_analyst",
            "risk_anomaly_agent",
        ],
    )
    claim_chunk = make_chunk(
        filename="incident_report.pdf",
        text="Incident date: April 2, 2026.",
        page_number=2,
    )
    policy_chunk = make_chunk(
        filename="policy.pdf",
        text="Policy passage concerning the reported incident.",
        page_number=4,
    )
    estimate_chunk = make_chunk(
        filename="estimate.pdf",
        text="Estimate records repairs dated April 3, 2026.",
        page_number=3,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[policy_chunk]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[claim_chunk]),
    )

    intake_payload = {"summary": "Synthetic intake result."}
    evidence_payload = {"summary": "Synthetic evidence result."}
    policy_payload = {"summary": "Synthetic policy result."}
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_documents",
        MagicMock(return_value=model_result(intake_payload)),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        MagicMock(return_value=model_result(evidence_payload)),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(return_value=model_result(policy_payload)),
    )
    monkeypatch.setattr(
        graph_module,
        "get_document_evidence_chunks",
        MagicMock(return_value=[estimate_chunk]),
    )
    estimate_output = RepairEstimateAnalystOutput(
        estimate_status="complete",
        valid_line_subtotal=Decimal("250.00"),
        complete_estimate_total=Decimal("250.00"),
        source_data_complete=True,
        calculation_complete=True,
        human_review_required=True,
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_repair_estimate",
        MagicMock(return_value=estimate_output),
    )
    risk_output = make_risk_output(estimate_chunk)
    risk_analyst = MagicMock(return_value=risk_output)
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        risk_analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Compare claim documents and estimate dates.",
        repair_estimate_document_id=estimate_chunk.document_id,
    )

    assert "risk_anomaly_agent" in (
        supervisor.call_args.kwargs["available_analysts"]
    )
    risk_analyst.assert_called_once()
    risk_kwargs = risk_analyst.call_args.kwargs
    assert risk_kwargs["claim_facts"] == {
        "claim_type": facts["claim_type"],
        "loss_date": facts["loss_date"],
        "status": facts["status"],
    }
    assert risk_kwargs["completed_analyst_outputs"] == {
        "intake_analysis": intake_payload,
        "evidence_analysis": evidence_payload,
        "policy_analysis": policy_payload,
        "repair_estimate_analysis": estimate_output.model_dump(mode="json"),
    }
    evidence_by_id = {
        evidence["chunk_id"]: evidence
        for evidence in risk_kwargs["claim_evidence"]
    }
    for chunk in (claim_chunk, policy_chunk, estimate_chunk):
        retrieved = evidence_by_id[str(chunk.chunk_id)]
        assert retrieved["document_id"] == str(chunk.document_id)
        assert retrieved["filename"] == chunk.filename
        assert retrieved["page_number"] == chunk.page_number
        assert retrieved["text"] == chunk.text
    policy_evidence = evidence_by_id[str(policy_chunk.chunk_id)]
    assert policy_evidence["clause_id"] is None
    assert policy_evidence["clause_identifier"] is None
    assert policy_evidence["clause_category"] is None
    assert policy_evidence["verification_status"] is None
    assert policy_evidence["policy_version"] is None
    assert output["risk_analysis_status"] == "completed"
    assert output["risk_analysis"]["human_review_required"] is True
    source = output["risk_analysis"]["anomalies"][0]["sources"][0]
    assert source == {
        "evidence_id": str(estimate_chunk.chunk_id),
        "document_id": str(estimate_chunk.document_id),
        "filename": estimate_chunk.filename,
        "page_number": estimate_chunk.page_number,
    }
    assert output["result"]["risk_analysis"] == output["risk_analysis"]
    assert output["result"]["human_review_required"] is True


def test_risk_agent_is_not_invoked_when_not_selected(monkeypatch):
    """Unselected risk analysis remains skipped."""
    employee_id, claim_id, _, _ = setup_plan(
        monkeypatch,
        ["policy_analyst"],
    )
    claim_chunk = make_chunk(
        filename="claim.pdf",
        text="Claim source statement.",
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[claim_chunk]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(
            return_value=model_result(
                {"summary": "Policy output.", "human_review_required": True}
            )
        ),
    )
    risk_analyst = MagicMock()
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        risk_analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review policy wording.",
    )

    assert output["risk_analysis_status"] == "skipped"
    risk_analyst.assert_not_called()


def test_risk_agent_is_unavailable_when_claim_evidence_retrieval_fails(
    monkeypatch,
):
    """Unavailable authorized evidence prevents selection and execution."""
    employee_id, claim_id, _, supervisor = setup_plan(
        monkeypatch,
        ["policy_analyst"],
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(
            side_effect=EvidenceRetrievalError("Synthetic retrieval failure.")
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    risk_analyst = MagicMock()
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        risk_analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review claim documents.",
    )

    assert "risk_anomaly_agent" not in (
        supervisor.call_args.kwargs["available_analysts"]
    )
    assert output["risk_analysis_status"] == "skipped"
    risk_analyst.assert_not_called()


def test_risk_agent_failure_preserves_completed_analyst_results(
    monkeypatch,
):
    """A Risk-agent error cannot erase earlier evidence or policy results."""
    employee_id, claim_id, _, _ = setup_plan(
        monkeypatch,
        ["evidence_analyst", "policy_analyst", "risk_anomaly_agent"],
    )
    claim_chunk = make_chunk(
        filename="claim.pdf",
        text="Claim evidence statement.",
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[claim_chunk]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    evidence_payload = {"summary": "Evidence result retained."}
    policy_payload = {"summary": "Policy result retained."}
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        MagicMock(return_value=model_result(evidence_payload)),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(return_value=model_result(policy_payload)),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        MagicMock(side_effect=RiskAnomalyAgentError("Synthetic failure.")),
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review claim evidence and policy.",
    )

    assert output["evidence_analysis"] == evidence_payload
    assert output["policy_analysis"] == policy_payload
    assert output["risk_analysis"] is None
    assert output["risk_analysis_status"] == "unavailable"
    assert output["result"]["evidence_analysis"] == evidence_payload
    assert output["result"]["policy_analysis"] == policy_payload
    assert output["result"]["human_review_required"] is True
    assert any(
        "Risk & Anomaly analysis is temporarily unavailable" in item
        for item in output["result"]["limitations"]
    )


def test_risk_agent_handles_forced_empty_context_without_llm(monkeypatch):
    """An invalid forced selection with empty evidence returns insufficiency."""
    employee_id, claim_id, _, _ = setup_plan(
        monkeypatch,
        ["risk_anomaly_agent"],
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    risk_analyst = MagicMock()
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        risk_analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the claim.",
    )

    assert output["risk_analysis_status"] == "insufficient_evidence"
    assert output["risk_analysis"]["overall_status"] == (
        "insufficient_evidence"
    )
    risk_analyst.assert_not_called()
