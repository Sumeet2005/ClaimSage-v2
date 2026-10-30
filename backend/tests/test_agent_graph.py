"""Unit tests for the ClaimSage LangGraph investigation workflow."""

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents.graph import run_investigation
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.document_access import (
    PolicyDocumentAccessDeniedError,
)


def make_session() -> Session:
    """Create a mock database session without connecting to PostgreSQL."""
    return MagicMock(spec=Session)


def test_authorized_claim_returns_structured_investigation(
    monkeypatch,
) -> None:
    """An authorized claim produces claim facts and policy evidence."""
    employee_id = uuid4()
    claim_id = uuid4()
    session = make_session()
    task = "Investigate hospitalization coverage."

    facts = {
        "claim_id": str(claim_id),
        "claim_number": "CLM-TEST-001",
        "claim_type": "property",
        "status": "under_review",
        "summary": "Synthetic test claim.",
        "created_at": None,
    }

    policy_chunk = MagicMock()
    policy_chunk.chunk_id = uuid4()
    policy_chunk.document_id = uuid4()
    policy_chunk.filename = "synthetic_policy.pdf"
    policy_chunk.page_number = 1
    policy_chunk.chunk_index = 0
    policy_chunk.text = "Eligible hospitalization expenses are covered."
    policy_chunk.similarity = 0.82
    policy_chunk.embedding_model = "test-model"

    claim_retrieval = MagicMock(return_value=facts)
    policy_retrieval = MagicMock(return_value=[policy_chunk])

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        claim_retrieval,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    # Keep graph tests independent of the live Groq API.
    policy_analysis = MagicMock()
    policy_analysis.model_dump.return_value = {
        "summary": "Synthetic policy analysis.",
        "relevant_clauses": [],
        "coverage_indicators": [],
        "exclusions_and_conditions": [],
        "missing_information": [],
        "evidence_gaps": [],
        "overall_assessment": "potentially_supportive",
        "human_review_required": True,
    }

    analyst = MagicMock(return_value=policy_analysis)
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        analyst,
    )

    output = run_investigation(
        session=session,
        employee_id=employee_id,
        claim_id=claim_id,
        task=task,
    )

    claim_retrieval.assert_called_once_with(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
    )

    policy_retrieval.assert_called_once_with(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
        query=task,
        top_k=5,
        min_similarity=0.20,
    )

    assert output["error"] is None
    assert output["claim_facts"] == facts
    assert len(output["policy_evidence"]) == 1
    assert output["result"] is not None

    assert (
        output["result"]["evidence_status"]
        == "claim_and_policy_evidence_retrieved"
    )
    assert output["result"]["policy_review"] == "evidence_retrieved"
    assert output["result"]["human_review_required"] is True

    evidence = output["result"]["policy_evidence"][0]

    assert evidence["filename"] == "synthetic_policy.pdf"
    assert evidence["page_number"] == 1
    assert evidence["similarity"] == 0.82
    assert evidence["text"] == (
        "Eligible hospitalization expenses are covered."
    )


def test_inaccessible_claim_returns_safe_error(monkeypatch) -> None:
    """Authorization failure must prevent policy retrieval."""
    retrieve = MagicMock(
        side_effect=ClaimAccessDeniedError(
            "Claim not found or access denied."
        )
    )
    policy_retrieval = MagicMock()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        retrieve,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Investigate this claim.",
    )

    assert output["error"] == "Claim not found or access denied."
    assert output["claim_facts"] is None
    assert output["result"] is None
    assert output["policy_evidence"] == []

    policy_retrieval.assert_not_called()


def test_nonexistent_claim_uses_same_safe_error(monkeypatch) -> None:
    """A missing claim must not disclose whether a claim exists."""
    retrieve = MagicMock(
        side_effect=ClaimAccessDeniedError(
            "Claim not found or access denied."
        )
    )
    policy_retrieval = MagicMock()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        retrieve,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Check this claim.",
    )

    assert output["error"] == "Claim not found or access denied."
    assert output["claim_facts"] is None
    assert output["result"] is None
    assert output["policy_evidence"] == []

    policy_retrieval.assert_not_called()


def test_invalid_employee_uuid_returns_safe_error(monkeypatch) -> None:
    """Malformed employee identifiers must not reach retrieval tools."""
    retrieve = MagicMock()
    policy_retrieval = MagicMock()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        retrieve,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = graph_module.build_investigation_graph().invoke(
        {
            "employee_id": "not-a-uuid",
            "claim_id": str(uuid4()),
            "task": "Investigate this claim.",
            "claim_facts": None,
            "policy_evidence": [],
            "result": None,
            "error": None,
        },
        context={"session": make_session()},
    )

    assert output["error"] == "Claim not found or access denied."
    assert output["claim_facts"] is None
    assert output["result"] is None

    retrieve.assert_not_called()
    policy_retrieval.assert_not_called()


def test_invalid_claim_uuid_returns_safe_error(monkeypatch) -> None:
    """Malformed claim identifiers must not reach retrieval tools."""
    retrieve = MagicMock()
    policy_retrieval = MagicMock()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        retrieve,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = graph_module.build_investigation_graph().invoke(
        {
            "employee_id": str(uuid4()),
            "claim_id": "not-a-uuid",
            "task": "Investigate this claim.",
            "claim_facts": None,
            "policy_evidence": [],
            "result": None,
            "error": None,
        },
        context={"session": make_session()},
    )

    assert output["error"] == "Claim not found or access denied."
    assert output["claim_facts"] is None
    assert output["result"] is None

    retrieve.assert_not_called()
    policy_retrieval.assert_not_called()


def test_empty_task_is_rejected_without_retrieval(monkeypatch) -> None:
    """An empty task must not call either retrieval service."""
    retrieve = MagicMock()
    policy_retrieval = MagicMock()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        retrieve,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="   ",
    )

    assert output["error"] == "An investigation task is required."
    assert output["claim_facts"] is None
    assert output["result"] is None
    assert output["policy_evidence"] == []

    retrieve.assert_not_called()
    policy_retrieval.assert_not_called()


def test_policy_retrieval_failure_does_not_create_unsupported_result(
    monkeypatch,
) -> None:
    """Retrieval failure must be reported without inventing evidence."""
    employee_id = uuid4()
    claim_id = uuid4()
    session = make_session()

    facts = {
        "claim_id": str(claim_id),
        "claim_number": "CLM-TEST-002",
        "claim_type": "property",
        "status": "under_review",
        "summary": "Synthetic test claim.",
        "created_at": None,
    }

    claim_retrieval = MagicMock(return_value=facts)

    policy_retrieval = MagicMock(
        side_effect=graph_module.PolicyRetrievalError(
            "Database unavailable."
        )
    )

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        claim_retrieval,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        policy_retrieval,
    )

    output = run_investigation(
        session=session,
        employee_id=employee_id,
        claim_id=claim_id,
        task="Investigate this claim.",
    )

    claim_retrieval.assert_called_once()

    policy_retrieval.assert_called_once_with(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
        query="Investigate this claim.",
        top_k=5,
        min_similarity=0.20,
    )

    assert output["error"] == (
        "Policy evidence retrieval is temporarily unavailable."
    )
    assert output["claim_facts"] == facts
    assert output["policy_evidence"] == []
    assert output["result"] is None


def test_policy_document_access_denied_returns_safe_error(
    monkeypatch,
) -> None:
    """Document authorization failures must not expose policy evidence."""
    employee_id = uuid4()
    claim_id = uuid4()
    facts = {
        "claim_id": str(claim_id),
        "claim_number": "CLM-TEST-003",
        "claim_type": "property",
        "status": "under_review",
        "summary": "Synthetic test claim.",
        "created_at": None,
    }

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(
            side_effect=PolicyDocumentAccessDeniedError(
                "Policy document access denied."
            )
        ),
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Investigate this claim.",
    )

    assert output["error"] == "Policy document access denied."
    assert output["claim_facts"] is None
    assert output["policy_evidence"] == []
    assert output["result"] is None