"""Integration tests for the LangGraph Policy Analyst workflow."""

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import policy_analyst as policy_analyst_module
from claimsage.agents.graph import run_investigation
from claimsage.agents.policy_analyst import PolicyAnalystError


def make_session() -> Session:
    """Create a mock database session."""
    return MagicMock(spec=Session)


def make_facts(claim_id):
    """Create synthetic claim facts."""
    return {
        "claim_id": str(claim_id),
        "claim_number": "CLM-INTEGRATION-001",
        "claim_type": "health",
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
    return chunk


def mock_retrieval(monkeypatch, facts, chunks):
    """Mock authorized claim and policy retrieval."""
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
        "relevant_clauses": [
            {
                "finding": "Hospitalization expenses may be covered.",
                "supporting_evidence_ids": [
                    str(chunk.chunk_id)
                ],
                "explanation": (
                    "The passage explicitly refers to eligible "
                    "hospitalization expenses."
                ),
                "confidence": "high",
            }
        ],
        "coverage_indicators": [
            "Eligible hospitalization expenses are mentioned."
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
    assert output["ai_analysis_status"] == "completed"
    assert output["policy_analysis"]["overall_assessment"] == (
        "insufficient_evidence"
    )
    assert output["policy_analysis"]["relevant_clauses"] == []
    assert output["result"]["policy_review"] == (
        "no_relevant_evidence_found"
    )


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
