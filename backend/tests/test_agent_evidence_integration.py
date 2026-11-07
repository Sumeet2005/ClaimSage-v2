"""Integration tests for the LangGraph Evidence Analyst workflow."""

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents.evidence_analyst import EvidenceAnalystError
from claimsage.agents.graph import run_investigation
from claimsage.agents.schemas import ReviewReportOutput, SupervisorPlan
from claimsage.rag.evidence_retrieval_service import EvidenceRetrievalError


def make_session() -> Session:
    """Create a mock database session."""
    return MagicMock(spec=Session)


def make_facts(claim_id):
    """Create synthetic authorized claim facts."""
    return {
        "claim_id": str(claim_id),
        "claim_number": "CLM-EVIDENCE-001",
        "claim_type": "health",
        "policy_identifier": "TEST-HEALTH-POLICY",
        "status": "under_review",
        "summary": "Synthetic hospitalization claim.",
        "created_at": None,
    }


def make_evidence_chunk():
    """Create a synthetic retrieved claim evidence chunk."""
    chunk = MagicMock()
    chunk.chunk_id = uuid4()
    chunk.document_id = uuid4()
    chunk.filename = "synthetic_hospital_record.pdf"
    chunk.page_number = 2
    chunk.chunk_index = 0
    chunk.text = "Patient was admitted for emergency treatment."
    chunk.similarity = 0.89
    chunk.embedding_model = "test-model"
    chunk.extraction_method = "native"
    chunk.ocr_confidence = None
    return chunk


def make_evidence_analysis():
    """Create a synthetic structured Evidence Analyst response."""
    analysis = MagicMock()
    analysis.model_dump.return_value = {
        "summary": "The evidence supports an emergency admission.",
        "factual_findings": [
            {
                "finding": "The patient was admitted for emergency treatment.",
                "supporting_evidence_ids": ["synthetic-chunk-id"],
                "explanation": "The document explicitly records admission.",
                "confidence": "high",
            }
        ],
        "timeline": [],
        "inconsistencies": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "supportive",
        "human_review_required": True,
    }
    return analysis


def make_policy_analysis():
    """Create a synthetic Policy Analyst response."""
    analysis = MagicMock()
    analysis.model_dump.return_value = {
        "summary": "No relevant policy passages were retrieved.",
        "relevant_clauses": [],
        "coverage_indicators": [],
        "exclusions_and_conditions": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "insufficient_evidence",
        "human_review_required": True,
    }
    return analysis


def setup_graph_retrieval(monkeypatch, claim_id, evidence_chunks):
    """Mock claim and policy retrieval for graph tests."""
    facts = make_facts(claim_id)

    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=[
                    "evidence_analyst",
                    "policy_analyst",
                ],
                routing_rationale="Both evidence domains are tested.",
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
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    evidence_retrieval = MagicMock(return_value=evidence_chunks)
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        evidence_retrieval,
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(return_value=make_policy_analysis()),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            return_value=ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="not_performed",
                evidence_scope_note="Synthetic report for evidence tests.",
                human_review_required=True,
            )
        ),
    )

    return facts, evidence_retrieval


def test_graph_runs_evidence_analyst_after_claim_evidence_retrieval(
    monkeypatch,
):
    """Retrieved claim evidence is passed to the Evidence Analyst."""
    employee_id = uuid4()
    claim_id = uuid4()
    task = "Review the hospitalization evidence."
    chunk = make_evidence_chunk()

    facts, retrieval = setup_graph_retrieval(
        monkeypatch,
        claim_id,
        [chunk],
    )

    analysis = make_evidence_analysis()
    analyst = MagicMock(return_value=analysis)
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task=task,
    )

    retrieval.assert_called_once()
    assert retrieval.call_args.kwargs["employee_id"] == employee_id
    assert retrieval.call_args.kwargs["claim_id"] == claim_id
    assert retrieval.call_args.kwargs["query"] == task

    analyst.assert_called_once()
    assert analyst.call_args.kwargs["task"] == task

    retrieved_evidence = analyst.call_args.kwargs["claim_evidence"]
    assert len(retrieved_evidence) == 1
    assert retrieved_evidence[0]["chunk_id"] == str(chunk.chunk_id)
    assert retrieved_evidence[0]["filename"] == chunk.filename
    assert retrieved_evidence[0]["page_number"] == 2
    assert retrieved_evidence[0]["extraction_method"] == "native"

    assert output["error"] is None
    assert output["claim_facts"] == facts
    assert output["evidence_analysis_status"] == "completed"
    assert output["evidence_analysis"]["overall_assessment"] == "supportive"
    assert output["result"]["claim_evidence"] == output["claim_evidence"]
    assert output["result"]["evidence_analysis"] == output["evidence_analysis"]
    assert output["result"]["human_review_required"] is True


def test_graph_handles_no_claim_evidence(monkeypatch):
    """Empty claim evidence is analyzed without inventing findings."""
    employee_id = uuid4()
    claim_id = uuid4()

    _, retrieval = setup_graph_retrieval(monkeypatch, claim_id, [])

    analysis = MagicMock()
    analysis.model_dump.return_value = {
        "summary": "No claim evidence was retrieved.",
        "factual_findings": [],
        "timeline": [],
        "inconsistencies": [],
        "missing_information": [],
        "evidence_gaps": ["No supporting claim documents were found."],
        "overall_assessment": "insufficient_evidence",
        "human_review_required": True,
    }

    analyst = MagicMock(return_value=analysis)
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the hospitalization evidence.",
    )

    retrieval.assert_called_once()
    analyst.assert_called_once()
    assert analyst.call_args.kwargs["claim_evidence"] == []

    assert output["error"] is None
    assert output["claim_evidence"] == []
    assert output["evidence_analysis_status"] == "completed"
    assert output["evidence_analysis"]["overall_assessment"] == (
        "insufficient_evidence"
    )
    assert output["evidence_analysis"]["factual_findings"] == []
    assert output["result"]["human_review_required"] is True


def test_graph_handles_claim_evidence_retrieval_failure(monkeypatch):
    """Retrieval failure is isolated and does not stop policy analysis."""
    employee_id = uuid4()
    claim_id = uuid4()

    setup_graph_retrieval(monkeypatch, claim_id, [])

    retrieval = MagicMock(
        side_effect=EvidenceRetrievalError("Synthetic retrieval failure.")
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        retrieval,
    )

    analyst = MagicMock()
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the hospitalization evidence.",
    )

    retrieval.assert_called_once()
    analyst.assert_not_called()

    assert output["error"] is None
    assert output["claim_evidence"] == []
    assert output["evidence_analysis"] is None
    assert output["evidence_analysis_status"] == "unavailable"
    assert output["ai_analysis_status"] == "completed"
    assert output["result"]["evidence_analysis"] is None
    assert any(
        "Claim evidence retrieval is temporarily unavailable" in item
        for item in output["result"]["limitations"]
    )


def test_graph_preserves_claim_evidence_when_analyst_fails(monkeypatch):
    """Analyst failure retains retrieved evidence for manual review."""
    employee_id = uuid4()
    claim_id = uuid4()
    chunk = make_evidence_chunk()

    _, retrieval = setup_graph_retrieval(
        monkeypatch,
        claim_id,
        [chunk],
    )

    analyst = MagicMock(
        side_effect=EvidenceAnalystError("Synthetic analysis failure.")
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        analyst,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the hospitalization evidence.",
    )

    retrieval.assert_called_once()
    analyst.assert_called_once()

    assert output["error"] is None
    assert len(output["claim_evidence"]) == 1
    assert output["claim_evidence"][0]["chunk_id"] == str(chunk.chunk_id)
    assert output["evidence_analysis"] is None
    assert output["evidence_analysis_status"] == "unavailable"

    assert output["ai_analysis_status"] == "completed"
    assert output["result"]["claim_evidence"] == output["claim_evidence"]
    assert output["result"]["evidence_analysis"] is None
    assert output["result"]["human_review_required"] is True

    assert any(
        "AI claim evidence analysis is temporarily unavailable" in item
        for item in output["result"]["limitations"]
    )
