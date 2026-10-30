"""Controlled LangGraph workflow for claim investigation."""

from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy.orm import Session

from claimsage.agents.state import InvestigationState
from claimsage.rag.retrieval_service import (
    PolicyRetrievalError,
    search_policy_chunks,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.tools.claim_tools import retrieve_authorized_claim


class InvestigationContext(TypedDict):
    """Trusted context injected by the backend."""

    session: Session


def investigate(
    state: InvestigationState,
    runtime: Runtime[InvestigationContext],
) -> dict[str, object]:
    """Retrieve an authorized claim and supporting policy evidence."""

    if not state["task"].strip():
        return {
            "claim_facts": None,
            "policy_evidence": [],
            "result": None,
            "error": "An investigation task is required.",
        }

    try:
        employee_id = UUID(state["employee_id"])
        claim_id = UUID(state["claim_id"])

        facts = retrieve_authorized_claim(
            runtime.context["session"],
            employee_id=employee_id,
            claim_id=claim_id,
        )

    except (ValueError, ClaimAccessDeniedError):
        return {
            "claim_facts": None,
            "policy_evidence": [],
            "result": None,
            "error": "Claim not found or access denied.",
        }

    try:
        retrieved_chunks = search_policy_chunks(
            runtime.context["session"],
            query=state["task"],
            top_k=5,
            min_similarity=0.20,
        )

        policy_evidence: list[dict[str, object]] = [
            {
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "filename": chunk.filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "similarity": round(chunk.similarity, 4),
                "embedding_model": chunk.embedding_model,
            }
            for chunk in retrieved_chunks
        ]

        policy_review = (
            "evidence_retrieved"
            if policy_evidence
            else "no_relevant_evidence_found"
        )

        evidence_status = (
            "claim_and_policy_evidence_retrieved"
            if policy_evidence
            else "claim_retrieved_policy_evidence_not_found"
        )

        limitations = [
            "Only authorized claim fields were retrieved.",
            "Retrieved policy passages are supporting evidence, not a coverage determination.",
            "Policy-document access authorization is not yet independently implemented.",
            "No coverage, fraud, or settlement decision was made.",
            "Human review is required before any consequential action.",
        ]

        if not policy_evidence:
            limitations.append(
                "No sufficiently similar policy passages were found."
            )

        result: dict[str, object] = {
            "task": state["task"],
            "claim": facts,
            "policy_evidence": policy_evidence,
            "evidence_status": evidence_status,
            "policy_review": policy_review,
            "human_review_required": True,
            "limitations": limitations,
        }

        return {
            "claim_facts": facts,
            "policy_evidence": policy_evidence,
            "result": result,
            "error": None,
        }

    except PolicyRetrievalError:
        return {
            "claim_facts": facts,
            "policy_evidence": [],
            "result": None,
            "error": "Policy evidence retrieval is temporarily unavailable.",
        }


def build_investigation_graph():
    """Compile the workflow without requiring an LLM API key."""

    builder = StateGraph(
        InvestigationState,
        context_schema=InvestigationContext,
    )
    builder.add_node("investigate", investigate)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", END)

    return builder.compile()


def run_investigation(
    *,
    session: Session,
    employee_id: UUID,
    claim_id: UUID,
    task: str,
) -> InvestigationState:
    """Run one investigation with trusted database session context."""

    initial_state: InvestigationState = {
        "employee_id": str(employee_id),
        "claim_id": str(claim_id),
        "task": task,
        "claim_facts": None,
        "policy_evidence": [],
        "result": None,
        "error": None,
    }

    return build_investigation_graph().invoke(
        initial_state,
        context={"session": session},
    )
