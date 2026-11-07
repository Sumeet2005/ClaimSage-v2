"""Integration tests for the LangGraph Policy Analyst workflow."""

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import policy_analyst as policy_analyst_module
from claimsage.agents.graph import run_investigation
from claimsage.agents.policy_analyst import PolicyAnalystError
from claimsage.agents.schemas import ReviewReportOutput, SupervisorPlan


def make_session() -> Session:
    """Create a mock database session."""
    return MagicMock(spec=Session)


def make_facts(claim_id):
    """Create synthetic claim facts."""
    return {
        "claim_id": str(claim_id),
        "claim_number": "CLM-INTEGRATION-001",
        "claim_type": "health",
        "policy_identifier": "TEST-HEALTH-POLICY",
        "status": "under_review",
        "summary": "Synthetic integration test claim.",
        "created_at": None,
    }


def make_policy_chunk():
    """Create a synthetic policy chunk."""
    chunk = MagicMock()
    chunk.chunk_id = uuid4()
    chunk.document_id = uuid4()
    chunk.filename = "synthetic_health_policy.pdf"
    chunk.page_number = 3
    chunk.chunk_index = 0
    chunk.text = "Eligible hospitalization expenses are covered."
    chunk.similarity = 0.91
    chunk.embedding_model = "test-model"
    chunk.clause_id = uuid4()
    chunk.clause_identifier = "source-page-3-chunk-0"
    chunk.clause_category = "other"
    chunk.verification_status = "pending_review"
    chunk.policy_version = "synthetic-v1"
    return chunk


def mock_retrieval(monkeypatch, facts, chunks):
    """Mock authorized claim, policy retrieval, and specialist routing."""
    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=chunks),
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=["policy_analyst"],
                routing_rationale="Synthetic policy-only regression-test plan.",
                human_review_required=True,
            )
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            return_value=ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="not_performed",
                evidence_scope_note="Synthetic report for policy tests.",
                human_review_required=True,
            )
        ),
    )


def test_graph_runs_policy_analyst_after_retrieval(monkeypatch):
    """Successful retrieval is followed by structured AI analysis."""
    employee_id = uuid4()
    claim_id = uuid4()
    task = "Review hospitalization coverage."

    facts = make_facts(claim_id)
    chunk = make_policy_chunk()

    mock_retrieval(monkeypatch, facts, [chunk])

    analysis = MagicMock()
    analysis.model_dump.return_value = {
        "summary": "The retrieved passage indicates a potentially relevant coverage provision.",
        "summary_quotes": [
            {
                "evidence_id": str(chunk.chunk_id),
                "quote": chunk.text,
            }
        ],
        "assessment_quotes": [
            {
                "evidence_id": str(chunk.chunk_id),
                "quote": chunk.text,
            }
        ],
        "relevant_clauses": [
            {
                "finding": "Hospitalization expenses may be covered.",
                "supporting_evidence_ids": [
                    str(chunk.chunk_id)
                ],
                "supporting_quotes": [
                    {
                        "evidence_id": str(chunk.chunk_id),
                        "quote": chunk.text,
                    }
                ],
                "explanation": (
                    "The passage explicitly refers to eligible "
                    "hospitalization expenses."
                ),
                "confidence": "high",
            }
        ],
        "coverage_indicators": [
            {
                "conclusion": "Eligible hospitalization expenses are mentioned.",
                "supporting_evidence_ids": [str(chunk.chunk_id)],
                "supporting_quotes": [
                    {
                        "evidence_id": str(chunk.chunk_id),
                        "quote": chunk.text,
                    }
                ],
            }
        ],
        "exclusions_and_conditions": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "potentially_supportive",
        "human_review_required": True,
    }

    analyst = MagicMock(return_value=analysis)
    monkeypatch.setattr(graph_module, "analyze_policy", analyst)

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task=task,
    )

    analyst.assert_called_once()

    assert output["error"] is None
    assert output["ai_analysis_status"] == "completed"
    assert output["policy_analysis"]["overall_assessment"] == (
        "potentially_supportive"
    )
    assert output["result"]["policy_analysis"] == output["policy_analysis"]
    assert output["result"]["human_review_required"] is True


def test_graph_handles_no_policy_evidence_without_groq(monkeypatch):
    """No evidence produces a safe insufficient-evidence analysis."""
    employee_id = uuid4()
    claim_id = uuid4()

    facts = make_facts(claim_id)
    mock_retrieval(monkeypatch, facts, [])

    # Exercise the real analyze_policy function. It should return its
    # insufficient-evidence result without requesting a Groq model.
    model_factory = MagicMock()
    monkeypatch.setattr(
        policy_analyst_module,
        "get_chat_model",
        model_factory,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review hospitalization coverage.",
    )

    model_factory.assert_not_called()

    assert output["error"] is None
    assert output["ai_analysis_status"] == "insufficient_evidence"
    assert output["policy_analysis"]["overall_assessment"] == (
        "insufficient_evidence"
    )
    assert output["policy_analysis"]["relevant_clauses"] == []
    assert output["result"]["policy_review"] == "no_relevant_evidence_found"


def test_graph_reports_no_applicable_policy_without_retrieving_passages(
    monkeypatch,
):
    employee_id = uuid4()
    claim_id = uuid4()
    facts = make_facts(claim_id)
    mock_retrieval(monkeypatch, facts, [])
    applicability_check = MagicMock(return_value=False)
    policy_search = graph_module.search_policy_chunks
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        applicability_check,
    )
    monkeypatch.setattr(graph_module, "search_policy_chunks", policy_search)
    model_factory = MagicMock()
    monkeypatch.setattr(
        policy_analyst_module,
        "get_chat_model",
        model_factory,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review policy wording for this claim.",
    )

    applicability_check.assert_called_once()
    policy_search.assert_not_called()
    model_factory.assert_not_called()
    assert output["policy_retrieval_status"] == "no_applicable_policy"
    assert output["policy_evidence"] == []
    assert output["ai_analysis_status"] == "insufficient_evidence"
    assert output["policy_analysis"]["overall_assessment"] == (
        "insufficient_evidence"
    )
    assert output["result"]["policy_review"] == "insufficient_evidence"
    assert any(
        "exact matching policy identifier, insurance type, supported claim type"
        in limitation
        for limitation in output["result"]["limitations"]
    )


def test_graph_returns_skipped_policy_status_inside_result(monkeypatch):
    employee_id = uuid4()
    claim_id = uuid4()
    mock_retrieval(monkeypatch, make_facts(claim_id), [])
    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=["evidence_analyst"],
                routing_rationale="Use only the requested evidence review.",
                human_review_required=True,
            )
        ),
    )
    evidence_analysis = MagicMock()
    evidence_analysis.model_dump.return_value = {
        "summary": "No claim evidence was retrieved.",
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

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review available claim evidence.",
    )

    assert output["ai_analysis_status"] == "skipped"
    assert output["result"]["ai_analysis_status"] == "skipped"


def test_graph_preserves_evidence_when_groq_fails(monkeypatch):
    """AI failure must not discard successfully retrieved evidence."""
    employee_id = uuid4()
    claim_id = uuid4()

    facts = make_facts(claim_id)
    chunk = make_policy_chunk()

    mock_retrieval(monkeypatch, facts, [chunk])

    analyst = MagicMock(
        side_effect=PolicyAnalystError(
            "The Policy Analyst could not complete the model request."
        )
    )
    monkeypatch.setattr(graph_module, "analyze_policy", analyst)

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review hospitalization coverage.",
    )

    assert output["error"] is None
    assert output["ai_analysis_status"] == "unavailable"
    assert output["policy_analysis"] is None

    assert len(output["policy_evidence"]) == 1
    assert output["result"]["policy_evidence"] == output["policy_evidence"]
    assert output["result"]["policy_review"] == "evidence_retrieved"
    assert output["result"]["human_review_required"] is True

    assert any(
        "AI policy analysis is temporarily unavailable" in item
        for item in output["result"]["limitations"]
    )
