"""Integration tests for Repair Estimate Analyst graph routing."""

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import repair_estimate_analyst as analyst_module
from claimsage.agents.repair_estimate_analyst import (
    RepairEstimateAnalystError,
)
from claimsage.agents.schemas import (
    RepairEstimateAnalystOutput,
    RepairEstimateLineCalculation,
    RepairEstimateLineItem,
    RepairEstimateSourceReference,
    ReviewReportOutput,
    SupervisorPlan,
)
from claimsage.rag.evidence_retrieval_service import RetrievedEvidenceChunk


def make_session() -> Session:
    """Create a mock database session without connecting to PostgreSQL."""
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
                evidence_scope_note="Synthetic report for estimate tests.",
                human_review_required=True,
            )
        ),
    )


def make_facts(claim_id):
    """Create synthetic authorized claim facts."""
    return {
        "claim_id": str(claim_id),
        "claim_number": "CLM-ESTIMATE-001",
        "claim_type": "property",
        "policy_identifier": "TEST-PROPERTY-POLICY",
        "status": "under_review",
        "summary": "Synthetic estimate integration test.",
        "created_at": None,
    }


def make_chunk(document_id=None):
    """Create a synthetic complete-retrieval chunk with UUID provenance."""
    return RetrievedEvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id or uuid4(),
        filename="synthetic_repair_estimate.pdf",
        page_number=2,
        chunk_index=0,
        text="Replace roof shingles: quantity 10, unit price 25.00.",
        similarity=None,
        embedding_model=None,
        extraction_method="native",
        ocr_confidence=None,
    )


def make_estimate_analysis(chunk):
    """Create a synthetic analyst result retaining canonical provenance."""
    source = RepairEstimateSourceReference(
        evidence_id=str(chunk.chunk_id),
        document_id=str(chunk.document_id),
        filename=chunk.filename,
        page_number=chunk.page_number,
    )
    return RepairEstimateAnalystOutput(
        estimate_status="complete",
        line_items=[
            RepairEstimateLineItem(
                description="Replace roof shingles",
                quantity="10",
                unit_price="25.00",
                reported_amount="250.00",
                source_evidence_ids=[str(chunk.chunk_id)],
                sources=[source],
            )
        ],
        line_calculations=[
            RepairEstimateLineCalculation(
                line_item_index=0,
                calculated_total=Decimal("250.00"),
                valid=True,
            )
        ],
        valid_line_subtotal=Decimal("250.00"),
        complete_estimate_total=Decimal("250.00"),
        source_data_complete=True,
        calculation_complete=True,
        human_review_required=True,
    )


def setup_graph(monkeypatch, selected_analysts, document_id=None):
    """Mock all retrieval and Supervisor boundaries for a graph run."""
    employee_id = uuid4()
    claim_id = uuid4()
    facts = make_facts(claim_id)
    supervisor = MagicMock(
        return_value=SupervisorPlan(
            selected_analysts=selected_analysts,
            routing_rationale="Synthetic estimate-routing test.",
            human_review_required=True,
        )
    )
    monkeypatch.setattr(graph_module, "create_supervisor_plan", supervisor)
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    return employee_id, claim_id, facts, supervisor


def test_graph_selects_and_runs_repair_estimate_analyst(monkeypatch):
    """A trusted estimate document is fully retrieved before analysis."""
    employee_id = uuid4()
    claim_id = uuid4()
    document_id = uuid4()
    facts = make_facts(claim_id)
    chunk = make_chunk(document_id)
    session = make_session()
    supervisor = MagicMock(
        return_value=SupervisorPlan(
            selected_analysts=["repair_estimate_analyst"],
            routing_rationale="Review the available repair estimate.",
            human_review_required=True,
        )
    )
    monkeypatch.setattr(graph_module, "create_supervisor_plan", supervisor)
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    retrieval = MagicMock(return_value=[chunk])
    monkeypatch.setattr(
        graph_module,
        "get_document_evidence_chunks",
        retrieval,
    )
    analysis = make_estimate_analysis(chunk)
    analyst = MagicMock(return_value=analysis)
    monkeypatch.setattr(
        graph_module,
        "analyze_repair_estimate",
        analyst,
    )

    output = graph_module.run_investigation(
        session=session,
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the repair estimate.",
        repair_estimate_document_id=document_id,
    )

    assert "repair_estimate_analyst" in (
        supervisor.call_args.kwargs["available_analysts"]
    )
    assert "repair_estimate_document_id" not in supervisor.call_args.kwargs
    retrieval.assert_called_once_with(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    analyst.assert_called_once_with(
        task="Review the repair estimate.",
        estimate_evidence=[chunk],
        source_data_complete=True,
    )
    assert output["repair_estimate_document_id"] == str(document_id)
    assert output["repair_estimate_analysis_status"] == "completed"
    assert output["repair_estimate_analysis"]["complete_estimate_total"] == (
        "250.00"
    )
    assert output["repair_estimate_analysis"]["line_items"][0]["sources"][0] == {
        "evidence_id": str(chunk.chunk_id),
        "document_id": str(document_id),
        "filename": chunk.filename,
        "page_number": 2,
    }
    assert output["result"]["human_review_required"] is True


def test_graph_does_not_run_estimate_without_selected_agent_or_document(
    monkeypatch,
):
    """Repair analysis requires both Supervisor selection and trusted ID."""
    employee_id, claim_id, _, supervisor = setup_graph(
        monkeypatch,
        ["evidence_analyst"],
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    evidence_analysis = MagicMock()
    evidence_analysis.model_dump.return_value = {
        "summary": "Evidence summary.",
        "factual_findings": [],
        "timeline": [],
        "inconsistencies": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "insufficient_evidence",
        "human_review_required": True,
    }
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        MagicMock(return_value=evidence_analysis),
    )
    retrieval = MagicMock()
    analyst = MagicMock()
    monkeypatch.setattr(graph_module, "get_document_evidence_chunks", retrieval)
    monkeypatch.setattr(graph_module, "analyze_repair_estimate", analyst)

    output = graph_module.run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review claim evidence.",
    )

    assert "repair_estimate_analyst" not in (
        supervisor.call_args.kwargs["available_analysts"]
    )
    assert output["repair_estimate_analysis_status"] == "skipped"
    retrieval.assert_not_called()
    analyst.assert_not_called()


def test_empty_document_retrieval_returns_unavailable_without_llm(
    monkeypatch,
):
    """An empty processed-document result is not a completed estimate."""
    employee_id = uuid4()
    claim_id = uuid4()
    document_id = uuid4()
    facts = make_facts(claim_id)
    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=["repair_estimate_analyst"],
                routing_rationale="Review the available estimate.",
                human_review_required=True,
            )
        ),
    )
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
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "get_document_evidence_chunks",
        MagicMock(return_value=[]),
    )
    model_factory = MagicMock()
    monkeypatch.setattr(analyst_module, "get_chat_model", model_factory)

    output = graph_module.run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the estimate.",
        repair_estimate_document_id=document_id,
    )

    assert output["repair_estimate_analysis_status"] == "unavailable"
    assert output["repair_estimate_analysis"]["estimate_status"] == (
        "unavailable"
    )
    assert output["repair_estimate_analysis"]["human_review_required"] is True
    model_factory.assert_not_called()
    assert output["result"]["human_review_required"] is True
    assert any(
        "No processed estimate evidence was available" in item
        for item in output["result"]["limitations"]
    )


def test_repair_failure_preserves_prior_analyst_results(monkeypatch):
    """Estimate failures update only estimate status and limitations."""
    employee_id = uuid4()
    claim_id = uuid4()
    document_id = uuid4()
    facts = make_facts(claim_id)
    selected = [
        "evidence_analyst",
        "policy_analyst",
        "repair_estimate_analyst",
    ]
    supervisor = MagicMock(
        return_value=SupervisorPlan(
            selected_analysts=selected,
            routing_rationale="Review evidence and repair estimate.",
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
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    evidence_analysis = MagicMock()
    evidence_analysis.model_dump.return_value = {
        "summary": "Evidence analyst result retained.",
        "factual_findings": [],
        "timeline": [],
        "inconsistencies": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "insufficient_evidence",
        "human_review_required": True,
    }
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        MagicMock(return_value=evidence_analysis),
    )
    policy_analysis = MagicMock()
    policy_analysis.model_dump.return_value = {
        "summary": "Policy result retained.",
        "relevant_clauses": [],
        "coverage_indicators": [],
        "exclusions_and_conditions": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "insufficient_evidence",
        "human_review_required": True,
    }
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(return_value=policy_analysis),
    )
    monkeypatch.setattr(
        graph_module,
        "get_document_evidence_chunks",
        MagicMock(return_value=[make_chunk(document_id)]),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_repair_estimate",
        MagicMock(
            side_effect=RepairEstimateAnalystError(
                "Synthetic analysis failure."
            )
        ),
    )

    output = graph_module.run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review evidence and estimate.",
        repair_estimate_document_id=document_id,
    )

    assert output["evidence_analysis_status"] == "completed"
    assert output["evidence_analysis"]["summary"] == (
        "Evidence analyst result retained."
    )
    assert output["policy_analysis"]["summary"] == "Policy result retained."
    assert output["ai_analysis_status"] == "completed"
    assert output["repair_estimate_analysis"] is None
    assert output["repair_estimate_analysis_status"] == "unavailable"
    assert output["result"]["evidence_analysis"] == output["evidence_analysis"]
    assert output["result"]["policy_analysis"] == output["policy_analysis"]
    assert output["result"]["repair_estimate_analysis"] is None
    assert output["result"]["human_review_required"] is True
    assert any(
        "AI repair estimate analysis is temporarily unavailable" in item
        for item in output["result"]["limitations"]
    )
