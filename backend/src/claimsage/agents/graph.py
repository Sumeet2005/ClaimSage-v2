"""Controlled LangGraph workflow for claim investigation."""

from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy.orm import Session

from claimsage.agents.policy_analyst import (
    PolicyAnalystError,
    analyze_policy,
)
from claimsage.agents.state import InvestigationState
from claimsage.rag.retrieval_service import (
    PolicyRetrievalError,
    search_policy_chunks,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.document_access import (
    PolicyDocumentAccessDeniedError,
)
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
            "policy_analysis": None,
            "ai_analysis_status": None,
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
            "policy_analysis": None,
            "ai_analysis_status": None,
            "result": None,
            "error": "Claim not found or access denied.",
        }

    try:
        retrieved_chunks = search_policy_chunks(
            runtime.context["session"],
            employee_id=employee_id,
            claim_id=claim_id,
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
            "Only policy documents authorized for this employee and claim were searched.",
            "Retrieved policy passages are supporting evidence, not a coverage determination.",
            "No coverage, fraud, or settlement decision was made.",
            "Human review is required before any consequential action.",
        ]

        if not policy_evidence:
            limitations.append(
                "No sufficiently similar policy passages were found in accessible documents."
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
            "policy_analysis": None,
            "ai_analysis_status": "pending",
            "result": result,
            "error": None,
        }

    except ClaimAccessDeniedError:
        return {
            "claim_facts": None,
            "policy_evidence": [],
            "policy_analysis": None,
            "ai_analysis_status": None,
            "result": None,
            "error": "Claim not found or access denied.",
        }

    except PolicyDocumentAccessDeniedError:
        return {
            "claim_facts": None,
            "policy_evidence": [],
            "policy_analysis": None,
            "ai_analysis_status": None,
            "result": None,
            "error": "Policy document access denied.",
        }

    except PolicyRetrievalError:
        return {
            "claim_facts": facts,
            "policy_evidence": [],
            "policy_analysis": None,
            "ai_analysis_status": None,
            "result": None,
            "error": "Policy evidence retrieval is temporarily unavailable.",
        }


def run_policy_analyst(
    state: InvestigationState,
) -> dict[str, object]:
    """Run the Policy Analyst on retrieved evidence."""

    if state["result"] is None:
        return {}

    try:
        analysis = analyze_policy(
            task=state["task"],
            policy_evidence=state["policy_evidence"],
        )

        analysis_data = analysis.model_dump(mode="json")

        updated_result = {
            **state["result"],
            "policy_analysis": analysis_data,
            "ai_analysis_status": "completed",
        }

        return {
            "policy_analysis": analysis_data,
            "ai_analysis_status": "completed",
            "result": updated_result,
        }

    except PolicyAnalystError:
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "AI policy analysis is temporarily unavailable. "
            "Retrieved policy evidence is retained for manual review."
        )

        updated_result = {
            **state["result"],
            "policy_analysis": None,
            "ai_analysis_status": "unavailable",
            "limitations": limitations,
        }

        return {
            "policy_analysis": None,
            "ai_analysis_status": "unavailable",
            "result": updated_result,
        }


def build_investigation_graph():
    """Compile the workflow without requiring an LLM API key."""

    builder = StateGraph(
        InvestigationState,
        context_schema=InvestigationContext,
    )

    builder.add_node("investigate", investigate)
    builder.add_node("policy_analyst", run_policy_analyst)

    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "policy_analyst")
    builder.add_edge("policy_analyst", END)

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
        "policy_analysis": None,
        "ai_analysis_status": None,
        "result": None,
        "error": None,
    }

    return build_investigation_graph().invoke(
        initial_state,
        context={"session": session},
    )
