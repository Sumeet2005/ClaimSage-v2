"""Controlled LangGraph workflow for claim investigation."""

import logging
import time
from collections.abc import Callable, Mapping
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel
from sqlalchemy.orm import Session

from claimsage.agents.evidence_analyst import (
    EvidenceAnalystError,
    analyze_claim_evidence,
)
from claimsage.agents.intake_agent import (
    IntakeAgentError,
    analyze_claim_documents,
)
from claimsage.agents.llm import (
    provider_failure_category,
    safe_provider_error_metadata,
    safe_retry_metadata,
)
from claimsage.agents.policy_analyst import (
    PolicyAnalystError,
    analyze_policy,
)
from claimsage.agents.repair_estimate_analyst import (
    RepairEstimateAnalystError,
    analyze_repair_estimate,
)
from claimsage.agents.report_validation import (
    reconcile_specialist_missing_in_state,
)
from claimsage.agents.review_report_agent import (
    ReviewReportAgentError,
    analyze_review_report,
    build_fallback_partial_report,
)
from claimsage.agents.risk_anomaly_agent import (
    RiskAnomalyAgentError,
    analyze_risk_and_anomalies,
)
from claimsage.agents.schemas import (
    EvidenceAnalystOutput,
    IntakeDocumentOutput,
    PolicyAnalystOutput,
    RepairEstimateAnalystOutput,
    ReviewReportEvidenceChunk,
    ReviewReportInput,
    ReviewReportOutput,
    ReviewReportSpecialistInput,
    RiskAnomalyOutput,
)
from claimsage.agents.state import InvestigationState
from claimsage.agents.supervisor import (
    SupervisorError,
    create_supervisor_plan,
)
from claimsage.rag.evidence_retrieval_service import (
    EvidenceRetrievalError,
    get_document_evidence_chunks,
    resolve_repair_estimate_document_id,
    search_claim_evidence,
)
from claimsage.rag.retrieval_service import (
    PolicyRetrievalError,
    has_applicable_policy_documents,
    search_policy_chunks,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.document_access import (
    PolicyDocumentAccessDeniedError,
)
from claimsage.core.config import get_settings
from claimsage.tools.claim_tools import retrieve_authorized_claim
from claimsage.agents.llm import get_last_invocation_diagnostic

logger = logging.getLogger(__name__)


def _record_provider_failure(
    result: dict[str, object],
    *,
    stage: str,
    error: BaseException,
) -> dict[str, object]:
    """Keep only sanitized provider failure metadata in persisted state."""

    failure = {
        "stage": stage,
        "category": provider_failure_category(error),
    }
    status_code, provider_code = safe_provider_error_metadata(error)
    if status_code is not None:
        failure["status_code"] = status_code
    if provider_code is not None:
        failure["provider_code"] = provider_code
    failure.update(safe_retry_metadata(error))
    previous = result.get("provider_failures", [])
    failures = list(previous) if isinstance(previous, list) else []
    failures.append(failure)
    logger.warning(
        "AI stage failed (stage=%s, category=%s, error_type=%s).",
        stage,
        failure["category"],
        type(error).__name__,
    )
    return {**result, "provider_failures": failures}


def _clear_stage_provider_failure(
    result: dict[str, object],
    *,
    stage: str,
) -> dict[str, object]:
    """Remove stale provider_failures entries for a stage when it succeeds on retry/resumption."""
    previous = result.get("provider_failures")
    if not isinstance(previous, list) or not previous:
        return result
    filtered = [
        item
        for item in previous
        if not (isinstance(item, Mapping) and item.get("stage") == stage)
    ]
    return {**result, "provider_failures": filtered}


def _retrieve_uploaded_claim_documents(
    session: Session,
    *,
    claim_id: UUID,
) -> list[dict[str, object]]:
    """Safely query uploaded ClaimDocument records for source inventory tracking."""
    if type(session) is not Session:
        return []
    try:
        from sqlalchemy import select
        from claimsage.db.models import ClaimDocument

        docs = session.scalars(
            select(ClaimDocument).where(ClaimDocument.claim_id == claim_id)
        ).all()
        uploaded: list[dict[str, object]] = []
        for doc in docs:
            doc_id = getattr(doc, "id", None)
            fname = getattr(doc, "filename", None)
            proc = getattr(doc, "processing_status", "processed")
            if doc_id is not None and isinstance(fname, str) and fname.strip():
                uploaded.append(
                    {
                        "document_id": str(doc_id),
                        "filename": fname.strip(),
                        "processing_status": str(proc or "processed"),
                    }
                )
        return uploaded
    except Exception:
        return []


STAGE_TO_AGENT_MAP: dict[str, str] = {
    "intake_analysis": "intake_agent",
    "evidence_analysis": "evidence_analyst",
    "policy_analysis": "policy_analyst",
    "repair_estimate_analysis": "repair_estimate_analyst",
    "risk_analysis": "risk_anomaly_agent",
    "review_report": "review_report",
    "supervisor": "supervisor",
}


def _record_stage_diagnostic(
    result: dict[str, object],
    *,
    stage: str,
    diagnostic: dict[str, object],
) -> dict[str, object]:
    """Record safe diagnostic metadata for a specialist stage without PII."""
    diagnostics = dict(
        result.get("stage_diagnostics", {})
        if isinstance(result.get("stage_diagnostics"), dict)
        else {}
    )
    inv_diag = get_last_invocation_diagnostic() or {}
    inv_stage = inv_diag.get("stage")
    expected_agent = STAGE_TO_AGENT_MAP.get(stage, stage)

    # Only attach invocation metrics if this stage actually performed the LLM invocation
    inv_matches = bool(
        inv_stage
        and (
            inv_stage == stage
            or inv_stage == expected_agent
            or inv_stage == diagnostic.get("agent_name")
        )
    )
    is_skipped = diagnostic.get("status") == "skipped"

    if inv_matches and not is_skipped:
        estimated_input_tokens = inv_diag.get("estimated_input_tokens")
        actual_prompt_tokens = inv_diag.get("actual_prompt_tokens")
        actual_completion_tokens = inv_diag.get("actual_completion_tokens")
        execution_duration = inv_diag.get("execution_duration")
        retry_attempts = inv_diag.get("retry_attempts", 0)
        failure_category = inv_diag.get("category")
        status_code = inv_diag.get("status_code")
        provider_code = inv_diag.get("provider_code")
    else:
        estimated_input_tokens = None
        actual_prompt_tokens = None
        actual_completion_tokens = None
        execution_duration = None
        retry_attempts = 0
        failure_category = None
        status_code = None
        provider_code = None

    stage_status = diagnostic.get("status") or (
        inv_diag.get("status") if inv_matches else "unavailable"
    )

    combined: dict[str, object] = {
        "agent_name": diagnostic.get("agent_name"),
        "retrieval_strategy": diagnostic.get("retrieval_strategy"),
        "candidate_passages": diagnostic.get("candidate_passages", 0),
        "deduplicated_passages": diagnostic.get("deduplicated_passages", 0),
        "selected_passages": diagnostic.get("selected_passages", 0),
        "estimated_input_tokens": estimated_input_tokens,
        "actual_prompt_tokens": actual_prompt_tokens,
        "actual_completion_tokens": actual_completion_tokens,
        "execution_duration": execution_duration,
        "retry_attempts": retry_attempts,
        "status": stage_status,
        "failure_category": failure_category,
        "status_code": status_code,
        "provider_code": provider_code,
    }
    for k, v in diagnostic.items():
        if k not in combined or combined[k] is None:
            combined[k] = v

    if inv_matches and not is_skipped:
        for extra_key in (
            "provider",
            "model",
            "primary_provider",
            "primary_model",
            "fallback_used",
            "fallback_provider",
            "fallback_model_used",
            "fallback_model_attempted",
            "fallback_failure_category",
            "fallback_status_code",
            "fallback_provider_code",
            "provider_retry_hint",
            "retry_after_seconds",
            "primary_model_failure_category",
            "primary_model_status_code",
            "primary_model_provider_code",
        ):
            if inv_diag.get(extra_key) is not None:
                combined[extra_key] = inv_diag[extra_key]

    diagnostics[stage] = combined
    return {**result, "stage_diagnostics": diagnostics}


def assemble_result(
    state: Mapping[str, object],
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    """Ensure specialist statuses (including policy_analysis_status) are persisted in result."""
    base = dict(result if isinstance(result, dict) else (state.get("result") or {}))
    policy_status = (
        base.get("policy_analysis_status")
        or base.get("ai_analysis_status")
        or state.get("policy_analysis_status")
        or state.get("ai_analysis_status")
    )
    if policy_status is not None:
        base["policy_analysis_status"] = policy_status
        base.setdefault("ai_analysis_status", policy_status)
    else:
        base.setdefault("policy_analysis_status", None)

    for status_key in (
        "supervisor_status",
        "intake_analysis_status",
        "evidence_analysis_status",
        "repair_estimate_analysis_status",
        "risk_analysis_status",
        "review_report_status",
    ):
        if base.get(status_key) is None and state.get(status_key) is not None:
            base[status_key] = state.get(status_key)
    return base


def _minimal_claim_context(
    claim_facts: dict[str, object] | None,
) -> dict[str, object] | None:
    """Exclude direct claim identifiers and narrative from provider context."""

    if claim_facts is None:
        return None
    allowed_fields = {"claim_type", "status", "loss_date"}
    return {
        key: value
        for key, value in claim_facts.items()
        if key in allowed_fields
    }


class InvestigationContext(TypedDict):
    """Trusted context injected by the backend."""

    session: Session


def investigate(
    state: InvestigationState,
    runtime: Runtime[InvestigationContext],
) -> dict[str, object]:
    """Retrieve an authorized claim and independently retrieve policy evidence."""

    if (
        isinstance(state.get("claim_facts"), dict)
        and isinstance(state.get("result"), dict)
        and state.get("policy_retrieval_status")
        in {"completed", "no_relevant_evidence", "no_applicable_policy"}
    ):
        return {}

    if not state["task"].strip():
        return {
            "claim_facts": None,
            "policy_evidence": [],
            "policy_retrieval_status": None,
            "policy_analysis": None,
            "repair_estimate_analysis": None,
            "repair_estimate_analysis_status": "skipped",
            "risk_analysis": None,
            "risk_analysis_status": "skipped",
            "ai_analysis_status": None,
            "review_report": None,
            "review_report_status": "skipped",
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
            "policy_retrieval_status": None,
            "policy_analysis": None,
            "repair_estimate_analysis": None,
            "repair_estimate_analysis_status": "skipped",
            "risk_analysis": None,
            "risk_analysis_status": "skipped",
            "ai_analysis_status": None,
            "review_report": None,
            "review_report_status": "skipped",
            "result": None,
            "error": "Claim not found or access denied.",
        }

    policy_evidence: list[dict[str, object]] = []
    policy_retrieval_status = "no_applicable_policy"

    try:
        if not isinstance(facts.get("claim_type"), str):
            raise ValueError("Authorized claim has no valid claim type.")

        if has_applicable_policy_documents(
            runtime.context["session"],
            employee_id=employee_id,
            claim_id=claim_id,
        ):
            retrieved_chunks = search_policy_chunks(
                runtime.context["session"],
                employee_id=employee_id,
                claim_id=claim_id,
                query=state["task"],
                top_k=5,
                min_similarity=0.20,
            )

            policy_evidence = [
                {
                    "chunk_id": str(chunk.chunk_id),
                    "document_id": str(chunk.document_id),
                    "filename": chunk.filename,
                    "source_url": getattr(chunk, "source_url", None),
                    "insurer_name": getattr(chunk, "insurer_name", None),
                    "product_name": getattr(chunk, "product_name", None),
                    "policy_identifier": facts.get("policy_identifier"),
                    "effective_from": (
                        chunk.effective_from.isoformat()
                        if getattr(chunk, "effective_from", None) is not None
                        else None
                    ),
                    "effective_to": (
                        chunk.effective_to.isoformat()
                        if getattr(chunk, "effective_to", None) is not None
                        else None
                    ),
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "similarity": round(chunk.similarity, 4),
                    "embedding_model": chunk.embedding_model,
                    "clause_id": (
                        str(clause_id)
                        if isinstance(
                            clause_id := getattr(chunk, "clause_id", None),
                            UUID,
                        )
                        else None
                    ),
                    "clause_identifier": (
                        clause_identifier
                        if isinstance(
                            clause_identifier := getattr(
                                chunk, "clause_identifier", None
                            ),
                            str,
                        )
                        else None
                    ),
                    "clause_category": (
                        clause_category
                        if isinstance(
                            clause_category := getattr(
                                chunk, "clause_category", None
                            ),
                            str,
                        )
                        else None
                    ),
                    "verification_status": (
                        verification_status
                        if isinstance(
                            verification_status := getattr(
                                chunk, "verification_status", None
                            ),
                            str,
                        )
                        else None
                    ),
                    "policy_version": (
                        policy_version
                        if isinstance(
                            policy_version := getattr(
                                chunk, "policy_version", None
                            ),
                            str,
                        )
                        else None
                    ),
                }
                for chunk in retrieved_chunks
            ]
            policy_retrieval_status = (
                "completed" if policy_evidence else "no_relevant_evidence"
            )

    except (PolicyDocumentAccessDeniedError, ClaimAccessDeniedError):
        policy_retrieval_status = "access_denied"

    except (PolicyRetrievalError, ValueError):
        policy_retrieval_status = "unavailable"

    policy_review = (
        "evidence_retrieved"
        if policy_retrieval_status == "completed"
        else "no_relevant_evidence_found"
        if policy_retrieval_status == "no_relevant_evidence"
        else "no_applicable_policy"
        if policy_retrieval_status == "no_applicable_policy"
        else "access_denied"
        if policy_retrieval_status == "access_denied"
        else "retrieval_unavailable"
    )

    evidence_status = (
        "claim_and_policy_evidence_retrieved"
        if policy_retrieval_status == "completed"
        else "claim_retrieved_policy_evidence_not_found"
        if policy_retrieval_status == "no_relevant_evidence"
        else "claim_retrieved_no_applicable_policy"
        if policy_retrieval_status == "no_applicable_policy"
        else "claim_retrieved_policy_access_denied"
        if policy_retrieval_status == "access_denied"
        else "claim_retrieved_policy_retrieval_unavailable"
    )

    limitations = [
        "Only authorized claim fields were retrieved.",
        "Retrieved policy passages are supporting evidence, not a coverage determination.",
        "No coverage, fraud, or settlement decision was made.",
        "Human review is required before any consequential action.",
    ]

    if policy_retrieval_status == "no_relevant_evidence":
        limitations.append(
            "No sufficiently similar policy passages were found in accessible documents."
        )
    elif policy_retrieval_status == "no_applicable_policy":
        limitations.append(
            "No single policy version with an exact matching policy "
            "identifier, insurance type, supported claim type, complete "
            "version metadata, and effective dates for the claim loss date "
            "was available. Unclassified, ambiguous, or unrelated policy "
            "passages were not used."
        )
    elif policy_retrieval_status == "access_denied":
        limitations.append(
            "Policy evidence access was denied. Claim facts were retained, "
            "but policy analysis cannot proceed."
        )
    elif policy_retrieval_status == "unavailable":
        limitations.append(
            "Policy evidence retrieval is temporarily unavailable. "
            "Claim facts were retained for the available investigation workflow."
        )

    resolved_estimate_doc_id = state.get("repair_estimate_document_id")
    if (
        resolved_estimate_doc_id is None
        and isinstance(facts.get("claim_type"), str)
        and str(facts.get("claim_type")).strip().lower() in {"auto", "motor"}
    ):
        auto_doc_id = resolve_repair_estimate_document_id(
            runtime.context["session"],
            employee_id=employee_id,
            claim_id=claim_id,
        )
        if isinstance(auto_doc_id, UUID):
            resolved_estimate_doc_id = str(auto_doc_id)

    policy_initial_status = (
        "pending"
        if policy_retrieval_status in {
            "completed",
            "no_relevant_evidence",
            "no_applicable_policy",
        }
        else "skipped"
    )
    result: dict[str, object] = {
        "task": state["task"],
        "claim": facts,
        "policy_evidence": policy_evidence,
        "policy_retrieval_status": policy_retrieval_status,
        "policy_analysis_status": policy_initial_status,
        "ai_analysis_status": policy_initial_status,
        "evidence_status": evidence_status,
        "policy_review": policy_review,
        "human_review_required": True,
        "limitations": limitations,
    }
    uploaded_docs = _retrieve_uploaded_claim_documents(
        runtime.context["session"],
        claim_id=claim_id,
    )
    if uploaded_docs:
        result["uploaded_documents"] = uploaded_docs
    if resolved_estimate_doc_id is not None:
        result["repair_estimate_document_id"] = resolved_estimate_doc_id

    state_update: dict[str, object] = {
        "claim_facts": facts,
        "policy_evidence": policy_evidence,
        "policy_retrieval_status": policy_retrieval_status,
        "policy_analysis": None,
        "policy_analysis_status": policy_initial_status,
        "ai_analysis_status": policy_initial_status,
        "result": result,
        "error": None,
    }
    if resolved_estimate_doc_id is not None:
        state_update["repair_estimate_document_id"] = resolved_estimate_doc_id
    return state_update

def retrieve_claim_evidence(
    state: InvestigationState,
    runtime: Runtime[InvestigationContext],
) -> dict[str, object]:
    """Retrieve evidence belonging only to the authorized claim."""

    if state["result"] is None:
        return {}

    if (
        state.get("claim_evidence_retrieval_status")
        in {"completed", "no_relevant_evidence"}
        and isinstance(state.get("claim_evidence"), list)
        and "claim_evidence" in state["result"]
    ):
        return {}

    try:
        retrieved_chunks = search_claim_evidence(
            runtime.context["session"],
            employee_id=UUID(state["employee_id"]),
            claim_id=UUID(state["claim_id"]),
            query=state["task"],
            top_k=5,
            min_similarity=0.20,
        )

        claim_evidence: list[dict[str, object]] = [
            {
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "filename": chunk.filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "similarity": round(chunk.similarity, 4),
                "embedding_model": chunk.embedding_model,
                "extraction_method": chunk.extraction_method,
                "ocr_confidence": chunk.ocr_confidence,
            }
            for chunk in retrieved_chunks
        ]

        retrieval_status = (
            "completed" if claim_evidence else "no_relevant_evidence"
        )
        total_candidate_chunks = len(claim_evidence)
        seen_chunks: set[str] = set()
        unique_claim_evidence: list[dict[str, object]] = []
        for ce in claim_evidence:
            cid = str(ce.get("chunk_id", ""))
            if cid and cid not in seen_chunks:
                seen_chunks.add(cid)
                unique_claim_evidence.append(ce)
        dedup_count = total_candidate_chunks - len(unique_claim_evidence)
        claim_evidence = unique_claim_evidence

        resolved_estimate_doc_id = state.get("repair_estimate_document_id")
        claim_facts = state.get("claim_facts")
        if (
            resolved_estimate_doc_id is None
            and isinstance(claim_facts, dict)
            and str(claim_facts.get("claim_type", "")).strip().lower()
            in {"auto", "motor"}
        ):
            for ce in claim_evidence:
                fn = str(ce.get("filename") or "").casefold()
                raw_doc_id = ce.get("document_id")
                if any(
                    kw in fn
                    for kw in (
                        "repair_estimate",
                        "repair-estimate",
                        "repair estimate",
                        "body_shop",
                        "bodyshop",
                    )
                ) and isinstance(raw_doc_id, str):
                    try:
                        UUID(raw_doc_id)
                        resolved_estimate_doc_id = raw_doc_id
                        break
                    except ValueError:
                        continue

        updated_result = {
            **state["result"],
            "claim_evidence": claim_evidence,
            "claim_evidence_retrieval_status": retrieval_status,
            "claim_evidence_candidate_count": total_candidate_chunks,
            "claim_evidence_deduplicated_count": dedup_count,
        }
        if resolved_estimate_doc_id is not None:
            updated_result["repair_estimate_document_id"] = (
                resolved_estimate_doc_id
            )
        ret_update: dict[str, object] = {
            "claim_evidence": claim_evidence,
            "claim_evidence_retrieval_status": retrieval_status,
            "claim_evidence_candidate_count": total_candidate_chunks,
            "claim_evidence_deduplicated_count": dedup_count,
            "result": updated_result,
        }
        if resolved_estimate_doc_id is not None:
            ret_update["repair_estimate_document_id"] = (
                resolved_estimate_doc_id
            )
        return ret_update

    except (ClaimAccessDeniedError, ValueError):
        retrieval_status = "unavailable"

    except EvidenceRetrievalError:
        retrieval_status = "unavailable"

    updated_result = {
        **state["result"],
        "claim_evidence": [],
        "claim_evidence_retrieval_status": retrieval_status,
    }
    return {
        "claim_evidence": [],
        "claim_evidence_retrieval_status": retrieval_status,
        "evidence_analysis_status": "unavailable",
        "result": updated_result,
    }


def run_intake_agent(
    state: InvestigationState,
) -> dict[str, object]:
    """Extract document fields and quality flags for human review."""

    if state["result"] is None:
        return {}

    if (
        state.get("intake_analysis_status") == "completed"
        and isinstance(state.get("intake_analysis"), dict)
    ):
        return {}

    if state["claim_evidence_retrieval_status"] == "unavailable":
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "Claim evidence retrieval is temporarily unavailable. "
            "No document intake analysis was performed."
        )
        updated_result = {
            **state["result"],
            "intake_analysis": None,
            "intake_analysis_status": "unavailable",
            "limitations": limitations,
        }
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="intake_analysis",
            diagnostic={
                "agent_name": "intake_agent",
                "retrieval_strategy": "intake_contextual",
                "candidate_passages": 0,
                "deduplicated_passages": 0,
                "selected_passages": 0,
                "status": "unavailable",
                "failure_category": "evidence_retrieval_unavailable",
            },
        )
        return {
            "intake_analysis": None,
            "intake_analysis_status": "unavailable",
            "result": updated_result,
        }

    try:
        analysis = analyze_claim_documents(
            task=state["task"],
            claim_evidence=state["claim_evidence"],
        )
        analysis_data = analysis.model_dump(mode="json")
        updated_result = {
            **state["result"],
            "intake_analysis": analysis_data,
            "intake_analysis_status": "completed",
        }
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="intake_analysis",
            diagnostic={
                "agent_name": "intake_agent",
                "retrieval_strategy": "intake_contextual",
                "candidate_passages": state.get("claim_evidence_candidate_count") or len(state.get("claim_evidence") or []),
                "deduplicated_passages": state.get("claim_evidence_deduplicated_count", 0),
                "selected_passages": len(state.get("claim_evidence") or []),
                "status": "completed",
            },
        )
        return _reconcile_state_update(
            state,
            {
                "intake_analysis": analysis_data,
                "intake_analysis_status": "completed",
                "result": updated_result,
            },
        )

    except IntakeAgentError as exc:
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "AI document intake analysis is temporarily unavailable. "
            "Retrieved claim evidence is retained for manual review."
        )
        updated_result = {
            **state["result"],
            "intake_analysis": None,
            "intake_analysis_status": "unavailable",
            "limitations": limitations,
        }
        updated_result = _record_provider_failure(
            updated_result,
            stage="intake_analysis",
            error=exc,
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="intake_analysis",
            diagnostic={
                "agent_name": "intake_agent",
                "retrieval_strategy": "intake_contextual",
                "candidate_passages": state.get("claim_evidence_candidate_count") or len(state.get("claim_evidence") or []),
                "deduplicated_passages": state.get("claim_evidence_deduplicated_count", 0),
                "selected_passages": len(state.get("claim_evidence") or []),
                "status": "unavailable",
                "failure_category": provider_failure_category(exc),
            },
        )
        return {
            "intake_analysis": None,
            "intake_analysis_status": "unavailable",
            "result": updated_result,
        }

def _apply_pacing_delay(stage: str) -> None:
    """Apply bounded delay before cloud LLM stages to stay under provider TPM limits."""
    settings = get_settings()
    if settings.app_env == "test":
        return
    last_diag = get_last_invocation_diagnostic() or {}
    gemini_key = getattr(settings, "gemini_api_key", None)
    has_gemini_fb = bool(
        gemini_key is not None
        and (
            gemini_key.get_secret_value().strip()
            if hasattr(gemini_key, "get_secret_value")
            else str(gemini_key).strip()
        )
    )
    has_fallback = bool(getattr(settings, "groq_fallback_model", None) or has_gemini_fb)
    if (
        last_diag.get("provider_retry_hint") is False
        or last_diag.get("category") == "quota_exceeded"
    ) and not has_fallback:
        return
    default_delay = 28.0 if stage in {"risk_anomaly_agent", "review_report"} else 20.0
    delay = getattr(settings, "groq_pacing_delay_seconds", default_delay)
    if delay > 0:
        logger.info(
            "Pacing cloud LLM invocation (stage=%s, delay=%.1fs)...",
            stage,
            delay,
        )
        time.sleep(delay)


def run_evidence_analyst(
    state: InvestigationState,
) -> dict[str, object]:
    """Analyze retrieved claim evidence without making claim decisions."""

    if state["result"] is None:
        return {}

    if (
        state.get("evidence_analysis_status") == "completed"
        and isinstance(state.get("evidence_analysis"), dict)
    ):
        return {}

    if state["evidence_analysis_status"] == "unavailable":
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "Claim evidence retrieval is temporarily unavailable. "
            "No evidence analysis was performed."
        )

        updated_result = {
            **state["result"],
            "claim_evidence": state["claim_evidence"],
            "evidence_analysis": None,
            "evidence_analysis_status": "unavailable",
            "limitations": limitations,
        }
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="evidence_analysis",
            diagnostic={
                "agent_name": "evidence_analyst",
                "retrieval_strategy": "evidence_analyst_contextual",
                "candidate_passages": 0,
                "deduplicated_passages": 0,
                "selected_passages": 0,
                "status": "unavailable",
                "failure_category": "evidence_retrieval_unavailable",
            },
        )

        return {
            "claim_evidence": state["claim_evidence"],
            "evidence_analysis": None,
            "evidence_analysis_status": "unavailable",
            "result": updated_result,
        }

    try:
        if state.get("claim_evidence"):
            _apply_pacing_delay("evidence_analyst")
        analysis = analyze_claim_evidence(
            task=state["task"],
            claim_evidence=state["claim_evidence"],
        )

        analysis_data = analysis.model_dump(mode="json")

        updated_result = {
            **state["result"],
            "claim_evidence": state["claim_evidence"],
            "evidence_analysis": analysis_data,
            "evidence_analysis_status": "completed",
        }
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="evidence_analysis",
            diagnostic={
                "agent_name": "evidence_analyst",
                "retrieval_strategy": "evidence_analyst_contextual",
                "candidate_passages": state.get("claim_evidence_candidate_count") or len(state.get("claim_evidence") or []),
                "deduplicated_passages": state.get("claim_evidence_deduplicated_count", 0),
                "selected_passages": len(state.get("claim_evidence") or []),
                "status": "completed",
            },
        )

        return _reconcile_state_update(
            state,
            {
                "claim_evidence": state["claim_evidence"],
                "evidence_analysis": analysis_data,
                "evidence_analysis_status": "completed",
                "result": updated_result,
            },
        )

    except EvidenceAnalystError as exc:
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "AI claim evidence analysis is temporarily unavailable. "
            "Retrieved claim evidence is retained for manual review."
        )

        updated_result = {
            **state["result"],
            "claim_evidence": state["claim_evidence"],
            "evidence_analysis": None,
            "evidence_analysis_status": "unavailable",
            "limitations": limitations,
        }
        updated_result = _record_provider_failure(
            updated_result,
            stage="evidence_analysis",
            error=exc,
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="evidence_analysis",
            diagnostic={
                "agent_name": "evidence_analyst",
                "retrieval_strategy": "evidence_analyst_contextual",
                "candidate_passages": state.get("claim_evidence_candidate_count") or len(state.get("claim_evidence") or []),
                "deduplicated_passages": state.get("claim_evidence_deduplicated_count", 0),
                "selected_passages": len(state.get("claim_evidence") or []),
                "status": "unavailable",
                "failure_category": provider_failure_category(exc),
            },
        )

        return {
            "claim_evidence": state["claim_evidence"],
            "evidence_analysis": None,
            "evidence_analysis_status": "unavailable",
            "result": updated_result,
        }


def run_policy_analyst(
    state: InvestigationState,
) -> dict[str, object]:
    """Run the Policy Analyst on retrieved evidence."""

    if state["result"] is None:
        return {}

    if (
        state.get("policy_analysis_status") in {"completed", "insufficient_evidence"}
        and isinstance(state.get("policy_analysis"), dict)
    ):
        return {}

    try:
        if state["policy_evidence"]:
            _apply_pacing_delay("policy_analyst")
        analysis = analyze_policy(
            task=state["task"],
            policy_evidence=state["policy_evidence"],
            claim_evidence=state.get("claim_evidence"),
            evidence_analysis=state.get("evidence_analysis"),
        )

        analysis_data = analysis.model_dump(mode="json")
        analysis_status = (
            "insufficient_evidence"
            if analysis.overall_assessment == "insufficient_evidence"
            else "completed"
        )

        updated_result = assemble_result(
            state,
            {
                **state["result"],
                "policy_analysis": analysis_data,
                "policy_analysis_status": analysis_status,
                "ai_analysis_status": analysis_status,
            },
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="policy_analysis",
            diagnostic={
                "agent_name": "policy_analyst",
                "retrieval_strategy": "policy_analyst_contextual",
                "candidate_passages": len(state.get("policy_evidence") or []),
                "selected_passages": len(state.get("policy_evidence") or []),
                "status": analysis_status,
            },
        )
        if analysis_status == "insufficient_evidence":
            updated_result["policy_review"] = (
                "insufficient_evidence"
                if state["policy_retrieval_status"] == "no_applicable_policy"
                else "no_relevant_evidence_found"
            )

        return _reconcile_state_update(
            state,
            {
                "policy_analysis": analysis_data,
                "policy_analysis_status": analysis_status,
                "ai_analysis_status": analysis_status,
                "result": updated_result,
            },
        )

    except PolicyAnalystError as exc:
        logger.warning("Policy Analyst failed: %s (cause: %s)", exc, getattr(exc, "__cause__", None))
        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "AI policy analysis is temporarily unavailable. "
            "Retrieved policy evidence is retained for manual review."
        )

        updated_result = assemble_result(
            state,
            {
                **state["result"],
                "policy_analysis": None,
                "policy_analysis_status": "unavailable",
                "ai_analysis_status": "unavailable",
                "limitations": limitations,
            },
        )
        updated_result = _record_provider_failure(
            updated_result,
            stage="policy_analysis",
            error=exc,
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="policy_analysis",
            diagnostic={
                "agent_name": "policy_analyst",
                "retrieval_strategy": "policy_analyst_contextual",
                "candidate_passages": len(state.get("policy_evidence") or []),
                "selected_passages": len(state.get("policy_evidence") or []),
                "status": "unavailable",
                "failure_category": provider_failure_category(exc),
            },
        )

        return {
            "policy_analysis": None,
            "policy_analysis_status": "unavailable",
            "ai_analysis_status": "unavailable",
            "result": updated_result,
        }


def run_repair_estimate_analyst(
    state: InvestigationState,
    runtime: Runtime[InvestigationContext],
) -> dict[str, object]:
    """Retrieve a complete authorized estimate document and analyze it."""

    if state["result"] is None:
        return {}

    if (
        state.get("repair_estimate_analysis_status") == "completed"
        and isinstance(state.get("repair_estimate_analysis"), dict)
    ):
        return {}

    document_id = state["repair_estimate_document_id"]
    if (
        "repair_estimate_analyst" not in state["selected_analysts"]
        or document_id is None
    ):
        updated_result = _record_stage_diagnostic(
            state["result"],
            stage="repair_estimate_analysis",
            diagnostic={
                "agent_name": "repair_estimate_analyst",
                "retrieval_strategy": "repair_estimate_contextual",
                "candidate_passages": 0,
                "selected_passages": 0,
                "status": "skipped",
            },
        )
        return {
            "repair_estimate_analysis": None,
            "repair_estimate_analysis_status": "skipped",
            "result": updated_result,
        }

    try:
        parsed_document_id = UUID(document_id)
        estimate_evidence = get_document_evidence_chunks(
            runtime.context["session"],
            employee_id=UUID(state["employee_id"]),
            claim_id=UUID(state["claim_id"]),
            document_id=parsed_document_id,
        )
    except (ValueError, ClaimAccessDeniedError, EvidenceRetrievalError):
        return _repair_estimate_failure(
            state,
            "Authorized repair estimate evidence could not be retrieved. "
            "Other analyst results were retained for human review.",
            repair_estimate_evidence=[],
            failure_category="evidence_retrieval_unavailable",
        )

    estimate_evidence_records = [
        {
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
        for chunk in estimate_evidence
    ]

    try:
        analysis = analyze_repair_estimate(
            task=state["task"],
            estimate_evidence=estimate_evidence,
            source_data_complete=True,
        )
        analysis_data = analysis.model_dump(mode="json")
    except RepairEstimateAnalystError as exc:
        failure = _repair_estimate_failure(
            state,
            "AI repair estimate analysis is temporarily unavailable. "
            "Retrieved estimate evidence and other analyst results were "
            "retained for human review.",
            repair_estimate_evidence=estimate_evidence_records,
            failure_category=provider_failure_category(exc),
        )
        result = failure.get("result")
        if isinstance(result, dict):
            failure["result"] = _record_provider_failure(
                result,
                stage="repair_estimate_analysis",
                error=exc,
            )
        return failure

    analysis_status = (
        "unavailable"
        if analysis.estimate_status == "unavailable"
        else "completed"
    )
    updated_result = {
        **state["result"],
        "repair_estimate_analysis": analysis_data,
        "repair_estimate_analysis_status": analysis_status,
        "human_review_required": True,
    }
    updated_result = _record_stage_diagnostic(
        updated_result,
        stage="repair_estimate_analysis",
        diagnostic={
            "agent_name": "repair_estimate_analyst",
            "retrieval_strategy": "repair_estimate_contextual",
            "candidate_passages": len(estimate_evidence_records or []),
            "selected_passages": len(estimate_evidence_records or []),
            "status": analysis_status,
        },
    )
    if analysis_status == "unavailable":
        limitations = list(updated_result.get("limitations", []))
        limitations.append(
            "No processed estimate evidence was available for analysis. "
            "Human review is required."
        )
        updated_result["limitations"] = limitations

    return _reconcile_state_update(
        state,
        {
            "repair_estimate_evidence": estimate_evidence_records,
            "repair_estimate_analysis": analysis_data,
            "repair_estimate_analysis_status": analysis_status,
            "result": updated_result,
        },
    )


def _repair_estimate_failure(
    state: InvestigationState,
    limitation: str,
    *,
    repair_estimate_evidence: list[dict[str, object]] | None = None,
    failure_category: str | None = None,
) -> dict[str, object]:
    """Record estimate-analysis failure without replacing other results."""

    if state["result"] is None:
        return {}
    limitations = list(state["result"].get("limitations", []))
    limitations.append(limitation)
    updated_result = {
        **state["result"],
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "unavailable",
        "human_review_required": True,
        "limitations": limitations,
    }
    updated_result = _record_stage_diagnostic(
        updated_result,
        stage="repair_estimate_analysis",
        diagnostic={
            "agent_name": "repair_estimate_analyst",
            "retrieval_strategy": "repair_estimate_contextual",
            "candidate_passages": len(repair_estimate_evidence or []),
            "selected_passages": len(repair_estimate_evidence or []),
            "status": "unavailable",
            "failure_category": failure_category,
        },
    )
    update: dict[str, object] = {
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "unavailable",
        "result": updated_result,
    }
    if repair_estimate_evidence is not None:
        update["repair_estimate_evidence"] = repair_estimate_evidence
    return update


def run_risk_anomaly_agent(
    state: InvestigationState,
) -> dict[str, object]:
    """Compare available retrieved evidence and analyst outputs for review."""

    if state["result"] is None:
        return {}

    if (
        state.get("risk_analysis_status") in {"completed", "insufficient_evidence"}
        and isinstance(state.get("risk_analysis"), dict)
    ):
        return {}
    if "risk_anomaly_agent" not in state["selected_analysts"]:
        updated_result = _record_stage_diagnostic(
            state["result"],
            stage="risk_analysis",
            diagnostic={
                "agent_name": "risk_anomaly_agent",
                "retrieval_strategy": "risk_anomaly_agent_contextual",
                "candidate_passages": 0,
                "selected_passages": 0,
                "status": "skipped",
            },
        )
        return {
            "risk_analysis": None,
            "risk_analysis_status": "skipped",
            "result": updated_result,
        }
    if state["claim_facts"] is None:
        return _risk_analysis_failure(
            state,
            "Authorized claim facts were unavailable for Risk & Anomaly "
            "analysis. Other analyst results were retained.",
            failure_category="claim_facts_unavailable",
        )
    if state["claim_evidence_retrieval_status"] == "unavailable":
        return _risk_analysis_failure(
            state,
            "Claim evidence retrieval was unavailable for Risk & Anomaly "
            "analysis. Other analyst results were retained.",
            failure_category="evidence_retrieval_unavailable",
        )
    if not state["claim_evidence"]:
        insufficient_output = RiskAnomalyOutput(
            overall_status="insufficient_evidence",
            human_review_required=True,
        ).model_dump(mode="json")
        updated_result = {
            **state["result"],
            "risk_analysis": insufficient_output,
            "risk_analysis_status": "insufficient_evidence",
            "human_review_required": True,
        }
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="risk_analysis",
            diagnostic={
                "agent_name": "risk_anomaly_agent",
                "retrieval_strategy": "risk_anomaly_agent_contextual",
                "candidate_passages": 0,
                "selected_passages": 0,
                "status": "insufficient_evidence",
            },
        )
        return {
            "risk_analysis": insufficient_output,
            "risk_analysis_status": "insufficient_evidence",
            "result": updated_result,
        }

    evidence_by_id: dict[str, dict[str, object]] = {}
    for evidence in (
        *state["claim_evidence"],
        *state["policy_evidence"],
        *state["repair_estimate_evidence"],
    ):
        evidence_id = evidence.get("chunk_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            return _risk_analysis_failure(
                state,
                "Retrieved evidence provenance was invalid for Risk & Anomaly "
                "analysis. Other analyst results were retained.",
                failure_category="invalid_evidence_provenance",
            )
        prior = evidence_by_id.get(evidence_id)
        if prior is not None:
            if any(
                prior.get(key) != evidence.get(key)
                for key in ("document_id", "filename", "page_number", "text")
            ):
                return _risk_analysis_failure(
                    state,
                    "Retrieved evidence contained conflicting provenance for "
                    "Risk & Anomaly analysis. Other analyst results were retained.",
                    failure_category="conflicting_evidence_provenance",
                )
            continue
        evidence_by_id[evidence_id] = evidence

    completed_outputs: dict[str, object] = {}
    analyst_results = (
        (
            "intake_analysis",
            state["intake_analysis"],
            state["intake_analysis_status"],
        ),
        (
            "evidence_analysis",
            state["evidence_analysis"],
            state["evidence_analysis_status"],
        ),
        (
            "policy_analysis",
            state["policy_analysis"],
            state["ai_analysis_status"],
        ),
        (
            "repair_estimate_analysis",
            state["repair_estimate_analysis"],
            state["repair_estimate_analysis_status"],
        ),
    )
    for analysis_key, analysis, status in analyst_results:
        if status == "completed" and isinstance(analysis, dict):
            completed_outputs[analysis_key] = analysis

    try:
        _apply_pacing_delay("risk_anomaly_agent")
        analysis = analyze_risk_and_anomalies(
            task=state["task"],
            claim_facts=_minimal_claim_context(state["claim_facts"]),
            claim_evidence=list(evidence_by_id.values()),
            completed_analyst_outputs=completed_outputs,
        )
        analysis_data = analysis.model_dump(mode="json")
    except (RiskAnomalyAgentError, ValueError) as exc:
        failure = _risk_analysis_failure(
            state,
            "AI Risk & Anomaly analysis is temporarily unavailable. "
            "Earlier analyst results were retained for human review.",
            candidate_passages=len(evidence_by_id),
            failure_category=provider_failure_category(exc),
        )
        result = failure.get("result")
        if isinstance(result, dict):
            failure["result"] = _record_provider_failure(
                result,
                stage="risk_analysis",
                error=exc,
            )
        return failure

    status = (
        "insufficient_evidence"
        if analysis.overall_status == "insufficient_evidence"
        else "completed"
    )
    updated_result = {
        **state["result"],
        "risk_analysis": analysis_data,
        "risk_analysis_status": status,
        "human_review_required": True,
    }
    updated_result = _record_stage_diagnostic(
        updated_result,
        stage="risk_analysis",
        diagnostic={
            "agent_name": "risk_anomaly_agent",
            "retrieval_strategy": "risk_anomaly_agent_contextual",
            "candidate_passages": len(evidence_by_id),
            "selected_passages": len(evidence_by_id),
            "status": status,
        },
    )
    return _reconcile_state_update(
        state,
        {
            "risk_analysis": analysis_data,
            "risk_analysis_status": status,
            "result": updated_result,
        },
    )


def _risk_analysis_failure(
    state: InvestigationState,
    limitation: str,
    *,
    candidate_passages: int = 0,
    failure_category: str | None = None,
) -> dict[str, object]:
    """Record a risk-agent failure without discarding previous results."""

    if state["result"] is None:
        return {}
    limitations = list(state["result"].get("limitations", []))
    limitations.append(limitation)
    updated_result = {
        **state["result"],
        "risk_analysis": None,
        "risk_analysis_status": "unavailable",
        "human_review_required": True,
        "limitations": limitations,
    }
    updated_result = _record_stage_diagnostic(
        updated_result,
        stage="risk_analysis",
        diagnostic={
            "agent_name": "risk_anomaly_agent",
            "retrieval_strategy": "risk_anomaly_agent_contextual",
            "candidate_passages": candidate_passages,
            "selected_passages": candidate_passages,
            "status": "unavailable",
            "failure_category": failure_category,
        },
    )
    return {
        "risk_analysis": None,
        "risk_analysis_status": "unavailable",
        "result": updated_result,
    }


def _report_specialist_input(
    *,
    name: str,
    analysis: object,
    status: str | None,
    selected: bool,
    output_model: type[BaseModel],
) -> ReviewReportSpecialistInput:
    """Validate specialist data before it enters the report input."""

    normalized_status = status
    if normalized_status is None:
        normalized_status = "pending" if selected else "skipped"
    if normalized_status not in {
        "completed",
        "insufficient_evidence",
        "unavailable",
        "failed",
        "skipped",
        "pending",
    }:
        raise ValueError(f"{name} has an unsupported execution status.")

    validated_analysis: dict[str, object] | None = None
    if normalized_status in {"completed", "insufficient_evidence"}:
        if not isinstance(analysis, dict):
            raise ValueError(
                f"{name} has no structured output for its execution status."
            )
        validated_analysis = output_model.model_validate(
            analysis
        ).model_dump(mode="json")
        if normalized_status == "completed" and any(
            validated_analysis.get(field) == "insufficient_evidence"
            for field in ("overall_status", "overall_assessment")
        ):
            normalized_status = "insufficient_evidence"

    limitations: list[str] = []
    if normalized_status == "insufficient_evidence":
        limitations.append(
            "The specialist returned an insufficient-evidence result; "
            "its analysis is included only as incomplete coverage."
        )
    elif normalized_status == "unavailable":
        limitations.append(
            "The specialist analysis was unavailable and is not included."
        )
    elif normalized_status == "failed":
        limitations.append(
            "The specialist analysis failed and is not included."
        )
    elif normalized_status == "skipped":
        limitations.append(
            "The specialist was skipped and did not provide an analysis."
        )
    elif normalized_status == "pending":
        limitations.append(
            "The specialist analysis remained pending and is not included."
        )

    return ReviewReportSpecialistInput(
        status=normalized_status,
        analysis=validated_analysis,
        limitations=limitations,
    )


def _retrieval_status_for_report(
    state: InvestigationState,
    evidence: list[ReviewReportEvidenceChunk],
) -> tuple[str, list[str]]:
    """Aggregate retrieval conservatively across the attempted sources.

    All successful searches yield ``completed``. Any failed or unattempted
    source alongside other outcomes yields ``limited``. All failed sources
    with no evidence yield ``unavailable``; no attempted sources yield
    ``not_performed``.
    """

    channels: list[tuple[str, str | None, set[str]]] = [
        (
            "Claim evidence",
            state["claim_evidence_retrieval_status"],
            {"completed", "no_relevant_evidence"},
        ),
        (
            "Policy evidence",
            state["policy_retrieval_status"],
            {
                "completed",
                "no_relevant_evidence",
                "no_applicable_policy",
            },
        ),
    ]
    if "repair_estimate_analyst" in state["selected_analysts"]:
        channels.append(
            (
                "Repair estimate evidence",
                state["repair_estimate_analysis_status"],
                {"completed", "insufficient_evidence"},
            )
        )

    failed_statuses = {"unavailable", "access_denied", "failed"}
    not_performed_statuses = {None, "skipped", "pending"}
    outcomes: list[str] = []
    limitations: list[str] = []
    for label, status, successful_statuses in channels:
        if status in successful_statuses:
            outcomes.append("successful")
            if status == "no_relevant_evidence":
                limitations.append(
                    f"{label} retrieval completed but returned no relevant "
                    "evidence."
                )
            elif status == "no_applicable_policy":
                limitations.append(
                    "No policy document with a verified matching policy "
                    "identifier and claim type was available."
                )
        elif status in failed_statuses:
            outcomes.append("failed")
            limitations.append(
                f"{label} retrieval or analysis was unavailable; its source "
                "coverage may be incomplete."
            )
        elif status in not_performed_statuses:
            outcomes.append("not_performed")
            limitations.append(
                f"{label} retrieval was not performed, so that source was "
                "not assessed."
            )
        else:
            raise ValueError(f"{label} has an unsupported retrieval status.")

    if not outcomes or all(item == "not_performed" for item in outcomes):
        return "not_performed", limitations
    if all(item == "failed" for item in outcomes) and not evidence:
        return "unavailable", limitations
    if "failed" in outcomes or "not_performed" in outcomes:
        return "limited", limitations
    return "completed", limitations


def _reconcile_state_update(
    state: InvestigationState,
    update: dict[str, object],
) -> dict[str, object]:
    """Reconcile specialist missing-information items against the shared evidence context."""
    merged = {**state, **update}
    reconciled = reconcile_specialist_missing_in_state(merged)
    if not reconciled:
        return update
    return {**update, **reconciled}


def _build_review_report_input(
    state: InvestigationState,
) -> ReviewReportInput:
    """Build report input only from authorized state and canonical retrievals."""
    reconciled_updates = reconcile_specialist_missing_in_state(state)
    if reconciled_updates:
        state = {**state, **reconciled_updates}  # type: ignore[assignment]

    evidence_by_id: dict[str, ReviewReportEvidenceChunk] = {}
    for record in (
        *state["claim_evidence"],
        *state["policy_evidence"],
        *state["repair_estimate_evidence"],
    ):
        evidence = ReviewReportEvidenceChunk.model_validate(record)
        prior = evidence_by_id.get(evidence.chunk_id)
        if prior is not None:
            provenance_fields = (
                "chunk_id",
                "document_id",
                "filename",
                "page_number",
                "chunk_index",
                "text",
            )
            optional_metadata_fields = (
                "embedding_model",
                "extraction_method",
                "ocr_confidence",
                "clause_id",
                "clause_identifier",
                "clause_category",
                "verification_status",
                "policy_version",
                "source_url",
                "policy_identifier",
                "insurer_name",
                "product_name",
                "effective_from",
                "effective_to",
            )
            if any(
                getattr(prior, field) != getattr(evidence, field)
                for field in provenance_fields
            ):
                raise ValueError(
                    "Retrieved evidence contains conflicting duplicate IDs."
                )
            merged = prior.model_dump(mode="python")
            for field in optional_metadata_fields:
                previous_value = getattr(prior, field)
                duplicate_value = getattr(evidence, field)
                if (
                    previous_value is not None
                    and duplicate_value is not None
                    and previous_value != duplicate_value
                ):
                    raise ValueError(
                        "Retrieved evidence contains conflicting duplicate IDs."
                    )
                if previous_value is None:
                    merged[field] = duplicate_value
            evidence_by_id[evidence.chunk_id] = (
                ReviewReportEvidenceChunk.model_validate(merged)
            )
            continue
        evidence_by_id[evidence.chunk_id] = evidence
    evidence = list(evidence_by_id.values())

    selected = set(state["selected_analysts"])
    specialists = {
        "intake_agent": _report_specialist_input(
            name="Intake Agent",
            analysis=state["intake_analysis"],
            status=state["intake_analysis_status"],
            selected="intake_agent" in selected,
            output_model=IntakeDocumentOutput,
        ),
        "evidence_analyst": _report_specialist_input(
            name="Evidence Analyst",
            analysis=state["evidence_analysis"],
            status=state["evidence_analysis_status"],
            selected="evidence_analyst" in selected,
            output_model=EvidenceAnalystOutput,
        ),
        "policy_analyst": _report_specialist_input(
            name="Policy Analyst",
            analysis=state["policy_analysis"],
            status=state["ai_analysis_status"],
            selected="policy_analyst" in selected,
            output_model=PolicyAnalystOutput,
        ),
        "repair_estimate_analyst": _report_specialist_input(
            name="Repair Estimate Analyst",
            analysis=state["repair_estimate_analysis"],
            status=state["repair_estimate_analysis_status"],
            selected="repair_estimate_analyst" in selected,
            output_model=RepairEstimateAnalystOutput,
        ),
        "risk_anomaly_agent": _report_specialist_input(
            name="Risk & Anomaly Agent",
            analysis=state["risk_analysis"],
            status=state["risk_analysis_status"],
            selected="risk_anomaly_agent" in selected,
            output_model=RiskAnomalyOutput,
        ),
    }
    retrieval_status, retrieval_limitations = (
        _retrieval_status_for_report(state, evidence)
    )
    specialist_usage: dict[str, list[str]] = {}
    repair_chunks = state.get("repair_estimate_evidence") or []
    if isinstance(repair_chunks, list) and repair_chunks:
        re_ids = [
            str(r.get("chunk_id"))
            for r in repair_chunks
            if isinstance(r, Mapping) and r.get("chunk_id")
        ]
        if re_ids:
            specialist_usage["repair_estimate_channel"] = re_ids
            if state.get("repair_estimate_analysis_status") in {
                "completed",
                "insufficient_evidence",
            }:
                specialist_usage["repair_estimate_analyst"] = re_ids

    uploaded_docs_list: list[dict[str, object]] = []
    shared_reconciled: list[dict[str, object]] = []
    if isinstance(state.get("result"), Mapping):
        raw_up = state["result"].get("uploaded_documents")
        if isinstance(raw_up, list):
            uploaded_docs_list = [
                dict(d) for d in raw_up if isinstance(d, Mapping)
            ]
        raw_rec = state["result"].get("shared_evidence_reconciliation")
        if isinstance(raw_rec, list):
            shared_reconciled = [
                dict(r) for r in raw_rec if isinstance(r, Mapping)
            ]

    structured_ctx: dict[str, object] | None = (
        dict(state["claim_facts"])
        if isinstance(state.get("claim_facts"), Mapping)
        else None
    )
    if shared_reconciled:
        if structured_ctx is None:
            structured_ctx = {}
        structured_ctx["shared_evidence_reconciliation"] = shared_reconciled

    return ReviewReportInput(
        claim_facts=_minimal_claim_context(state["claim_facts"]),
        structured_claim_context=structured_ctx,
        uploaded_documents=uploaded_docs_list,
        specialist_evidence_usage=specialist_usage,
        retrieved_evidence=evidence,
        evidence_retrieval_status=retrieval_status,
        evidence_retrieval_limitations=retrieval_limitations,
        **specialists,
    )


def run_review_report(
    state: InvestigationState,
) -> dict[str, object]:
    """Create an evidence-grounded report without changing analyst results."""

    if state["result"] is None:
        return {
            "review_report": None,
            "review_report_status": "skipped",
        }

    if (
        state.get("review_report_status") == "completed"
        and state.get("review_report") is not None
    ):
        return {}

    failure_stage = "input_build"
    try:
        report_input = _build_review_report_input(state)
        failure_stage = "agent_execution"
        _apply_pacing_delay("review_report")
        report = analyze_review_report(report_input=report_input)
        failure_stage = "output_validation"
        if not isinstance(report, ReviewReportOutput):
            raise ReviewReportAgentError(
                "The Review & Report Agent returned an invalid report."
            )
        report = ReviewReportOutput.model_validate(
            report.model_dump(mode="python")
        )
        if report.human_review_required is not True:
            raise ReviewReportAgentError(
                "The Review & Report Agent returned an invalid report."
            )
    except Exception as exc:
        status_code, _ = safe_provider_error_metadata(exc)
        logger.warning(
            "Review report generation failed at %s "
            "(category=%s, error_type=%s, status_code=%s).",
            failure_stage,
            provider_failure_category(exc),
            type(exc).__name__,
            status_code,
        )
        fallback_data = None
        fallback_status = "unavailable"
        try:
            if "report_input" in locals():
                fallback_report = build_fallback_partial_report(
                    report_input=report_input,
                    error_message=f"{provider_failure_category(exc)}: {type(exc).__name__}",
                )
                fallback_data = fallback_report.model_dump(mode="json")
                fallback_status = "incomplete"
        except Exception as fallback_exc:
            logger.warning("Could not construct fallback partial report: %s", fallback_exc)

        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "Review & Report generation is temporarily unavailable. "
            "Specialist results were retained for mandatory human review."
        )
        updated_result = {
            **state["result"],
            "review_report": None,
            "review_report_status": "unavailable",
            "human_review_required": True,
            "limitations": limitations,
        }
        if fallback_data is not None:
            updated_result["fallback_report"] = fallback_data
        updated_result = _record_provider_failure(
            updated_result,
            stage="review_report",
            error=exc,
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="review_report",
            diagnostic={
                "agent_name": "review_report_agent",
                "retrieval_strategy": "review_report_contextual",
                "status": "unavailable",
                "failure_category": provider_failure_category(exc),
            },
        )
        return {
            "review_report": None,
            "review_report_status": "unavailable",
            "result": updated_result,
        }

    report_status = (
        "incomplete"
        if report.overall_status == "incomplete"
        else "completed"
    )
    report_data = report.model_dump(mode="json")
    cleared_result = _clear_stage_provider_failure(
        state["result"],
        stage="review_report",
    )
    cleared_result.pop("fallback_report", None)
    if isinstance(cleared_result.get("limitations"), list):
        cleared_result["limitations"] = [
            lim
            for lim in cleared_result["limitations"]
            if isinstance(lim, str)
            and "Review & Report generation is temporarily unavailable" not in lim
        ]
    updated_result = assemble_result(
        state,
        {
            **cleared_result,
            "review_report": report_data,
            "review_report_status": report_status,
            "human_review_required": True,
        },
    )
    updated_result = _record_stage_diagnostic(
        updated_result,
        stage="review_report",
        diagnostic={
            "agent_name": "review_report_agent",
            "retrieval_strategy": "review_report_contextual",
            "status": report_status,
            "report_validation_status": report.report_validation_status,
            "report_completeness": report.report_completeness,
            "policy_verification_status": report.policy_verification_status,
            "validation_warnings": list(report.validation_warnings),
            "validation_failures": list(report.validation_failures),
        },
    )
    return {
        "review_report": report,
        "review_report_status": report_status,
        "result": updated_result,
    }


def run_supervisor(
    state: InvestigationState,
) -> dict[str, object]:
    """Create a controlled execution plan for available specialists."""

    if state["result"] is None:
        return {
            "selected_analysts": [],
            "supervisor_plan": None,
            "supervisor_status": "skipped",
            "intake_analysis_status": "skipped",
            "repair_estimate_analysis_status": "skipped",
        }

    if (
        state.get("supervisor_status") in {"completed", "fallback"}
        and state.get("selected_analysts")
        and "supervisor_status" in state["result"]
    ):
        return {}

    available_analysts = ["intake_agent", "evidence_analyst"]
    if state["repair_estimate_document_id"] is not None:
        available_analysts.append("repair_estimate_analyst")
    if (
        state["claim_facts"] is not None
        and state["claim_evidence_retrieval_status"] == "completed"
        and bool(state["claim_evidence"])
    ):
        available_analysts.append("risk_anomaly_agent")

    if state["policy_retrieval_status"] in {
        "completed",
        "no_relevant_evidence",
        "no_applicable_policy",
    }:
        available_analysts.append("policy_analyst")

    try:
        plan = create_supervisor_plan(
            task=state["task"],
            claim_facts_available=state["claim_facts"] is not None,
            policy_evidence_available=bool(state["policy_evidence"]),
            available_analysts=available_analysts,
        )
        selected_analysts = list(plan.selected_analysts)
        plan_data = plan.model_dump(mode="json")
        intake_status = (
            "pending"
            if "intake_agent" in selected_analysts
            else "skipped"
        )
        repair_estimate_status = (
            "pending"
            if (
                "repair_estimate_analyst" in selected_analysts
                and state["repair_estimate_document_id"] is not None
            )
            else "skipped"
        )
        risk_status = (
            "pending"
            if (
                "risk_anomaly_agent" in selected_analysts
                and state["claim_facts"] is not None
            )
            else "skipped"
        )
        policy_status = (
            state["ai_analysis_status"]
            if "policy_analyst" in selected_analysts
            else "skipped"
        )

        updated_result = assemble_result(
            state,
            {
                **state["result"],
                "supervisor_plan": plan_data,
                "supervisor_status": "completed",
                "policy_analysis_status": policy_status,
                "ai_analysis_status": policy_status,
                "intake_analysis": None,
                "intake_analysis_status": intake_status,
                "repair_estimate_analysis": None,
                "repair_estimate_analysis_status": repair_estimate_status,
                "risk_analysis": None,
                "risk_analysis_status": risk_status,
            },
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="supervisor",
            diagnostic={
                "agent_name": "supervisor",
                "retrieval_strategy": "supervisor_planning",
                "status": "completed",
            },
        )
        if repair_estimate_status == "skipped":
            updated_result = _record_stage_diagnostic(
                updated_result,
                stage="repair_estimate_analysis",
                diagnostic={
                    "agent_name": "repair_estimate_analyst",
                    "retrieval_strategy": "repair_estimate_contextual",
                    "candidate_passages": 0,
                    "selected_passages": 0,
                    "status": "skipped",
                },
            )

        return {
            "selected_analysts": selected_analysts,
            "supervisor_plan": plan_data,
            "supervisor_status": "completed",
            "evidence_analysis_status": (
                "unavailable"
                if state["evidence_analysis_status"] == "unavailable"
                else (
                    "pending"
                    if "evidence_analyst" in selected_analysts
                    else "skipped"
                )
            ),
            "intake_analysis_status": intake_status,
            "repair_estimate_analysis_status": repair_estimate_status,
            "risk_analysis_status": risk_status,
            "policy_analysis_status": policy_status,
            "ai_analysis_status": policy_status,
            "result": updated_result,
        }

    except SupervisorError as exc:
        # Preserve the previous workflow if Supervisor planning is unavailable.
        selected_analysts = list(available_analysts)

        limitations = list(state["result"].get("limitations", []))
        limitations.append(
            "Supervisor planning is temporarily unavailable. "
            "All currently available specialist analysts were selected "
            "as a controlled fallback."
        )
        intake_status = (
            "pending" if "intake_agent" in selected_analysts else "skipped"
        )
        repair_estimate_status = (
            "pending"
            if "repair_estimate_analyst" in selected_analysts
            and state["repair_estimate_document_id"] is not None
            else "skipped"
        )
        risk_status = (
            "pending"
            if "risk_anomaly_agent" in selected_analysts
            and state["claim_facts"] is not None
            else "skipped"
        )
        policy_status = (
            "pending" if "policy_analyst" in selected_analysts else "skipped"
        )

        updated_result = assemble_result(
            state,
            {
                **state["result"],
                "supervisor_plan": None,
                "supervisor_status": "fallback",
                "policy_analysis_status": policy_status,
                "ai_analysis_status": policy_status,
                "intake_analysis": None,
                "intake_analysis_status": intake_status,
                "repair_estimate_analysis": None,
                "repair_estimate_analysis_status": repair_estimate_status,
                "risk_analysis": None,
                "risk_analysis_status": risk_status,
                "limitations": limitations,
            },
        )
        updated_result = _record_provider_failure(
            updated_result,
            stage="supervisor",
            error=exc,
        )
        updated_result = _record_stage_diagnostic(
            updated_result,
            stage="supervisor",
            diagnostic={
                "agent_name": "supervisor",
                "retrieval_strategy": "supervisor_planning",
                "status": "fallback",
                "failure_category": provider_failure_category(exc),
            },
        )
        if repair_estimate_status == "skipped":
            updated_result = _record_stage_diagnostic(
                updated_result,
                stage="repair_estimate_analysis",
                diagnostic={
                    "agent_name": "repair_estimate_analyst",
                    "retrieval_strategy": "repair_estimate_contextual",
                    "candidate_passages": 0,
                    "selected_passages": 0,
                    "status": "skipped",
                },
            )

        return {
            "selected_analysts": selected_analysts,
            "supervisor_plan": None,
            "supervisor_status": "fallback",
            "evidence_analysis_status": (
                "unavailable"
                if state["evidence_analysis_status"] == "unavailable"
                else "pending"
            ),
            "intake_analysis_status": intake_status,
            "repair_estimate_analysis_status": repair_estimate_status,
            "risk_analysis_status": risk_status,
            "policy_analysis_status": policy_status,
            "ai_analysis_status": policy_status,
            "result": updated_result,
        }


def route_after_supervisor(state: InvestigationState) -> str:
    """Route to the first selected specialist."""

    if state["result"] is None:
        return END

    selected = state["selected_analysts"]

    if "intake_agent" in selected:
        return "intake_agent"
    if "evidence_analyst" in selected:
        return "evidence_analyst"

    if "policy_analyst" in selected:
        return "policy_analyst"

    if (
        "repair_estimate_analyst" in selected
        and state["repair_estimate_document_id"] is not None
    ):
        return "repair_estimate_analyst"
    if "risk_anomaly_agent" in selected:
        return "risk_anomaly_agent"

    return END


def route_after_intake_agent(state: InvestigationState) -> str:
    """Continue from Intake to any selected evidence or policy analysis."""

    if "evidence_analyst" in state["selected_analysts"]:
        return "evidence_analyst"
    if "policy_analyst" in state["selected_analysts"]:
        return "policy_analyst"
    if (
        "repair_estimate_analyst" in state["selected_analysts"]
        and state["repair_estimate_document_id"] is not None
    ):
        return "repair_estimate_analyst"
    if "risk_anomaly_agent" in state["selected_analysts"]:
        return "risk_anomaly_agent"
    return "review_report"


def route_after_evidence_analyst(
    state: InvestigationState,
) -> str:
    """Run policy analysis next when selected by the Supervisor."""

    if "policy_analyst" in state["selected_analysts"]:
        return "policy_analyst"

    if (
        "repair_estimate_analyst" in state["selected_analysts"]
        and state["repair_estimate_document_id"] is not None
    ):
        return "repair_estimate_analyst"
    if "risk_anomaly_agent" in state["selected_analysts"]:
        return "risk_anomaly_agent"

    return "review_report"


def route_after_policy_analyst(state: InvestigationState) -> str:
    """Run estimate analysis after Policy when it was selected."""

    if (
        "repair_estimate_analyst" in state["selected_analysts"]
        and state["repair_estimate_document_id"] is not None
    ):
        return "repair_estimate_analyst"
    if "risk_anomaly_agent" in state["selected_analysts"]:
        return "risk_anomaly_agent"

    return "review_report"


def route_after_repair_estimate_analyst(
    state: InvestigationState,
) -> str:
    """Run Risk & Anomaly last when the Supervisor selected it."""

    if "risk_anomaly_agent" in state["selected_analysts"]:
        return "risk_anomaly_agent"
    return "review_report"


def build_investigation_graph():
    """Compile the controlled Supervisor-led investigation workflow."""

    builder = StateGraph(
        InvestigationState,
        context_schema=InvestigationContext,
    )

    builder.add_node("investigate", investigate)
    builder.add_node("retrieve_claim_evidence", retrieve_claim_evidence)
    builder.add_node("supervisor", run_supervisor)
    builder.add_node("intake_agent", run_intake_agent)
    builder.add_node("evidence_analyst", run_evidence_analyst)
    builder.add_node("policy_analyst", run_policy_analyst)
    builder.add_node("repair_estimate_analyst", run_repair_estimate_analyst)
    builder.add_node("risk_anomaly_agent", run_risk_anomaly_agent)
    builder.add_node("review_report", run_review_report)

    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "retrieve_claim_evidence")
    builder.add_edge("retrieve_claim_evidence", "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "intake_agent": "intake_agent",
            "evidence_analyst": "evidence_analyst",
            "policy_analyst": "policy_analyst",
            "repair_estimate_analyst": "repair_estimate_analyst",
            "risk_anomaly_agent": "risk_anomaly_agent",
            "review_report": "review_report",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "intake_agent",
        route_after_intake_agent,
        {
            "evidence_analyst": "evidence_analyst",
            "policy_analyst": "policy_analyst",
            "repair_estimate_analyst": "repair_estimate_analyst",
            "risk_anomaly_agent": "risk_anomaly_agent",
            "review_report": "review_report",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "evidence_analyst",
        route_after_evidence_analyst,
        {
            "policy_analyst": "policy_analyst",
            "repair_estimate_analyst": "repair_estimate_analyst",
            "risk_anomaly_agent": "risk_anomaly_agent",
            "review_report": "review_report",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "policy_analyst",
        route_after_policy_analyst,
        {
            "repair_estimate_analyst": "repair_estimate_analyst",
            "risk_anomaly_agent": "risk_anomaly_agent",
            "review_report": "review_report",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "repair_estimate_analyst",
        route_after_repair_estimate_analyst,
        {
            "risk_anomaly_agent": "risk_anomaly_agent",
            "review_report": "review_report",
            END: END,
        },
    )
    builder.add_edge("risk_anomaly_agent", "review_report")
    builder.add_edge("review_report", END)

    return builder.compile()

def retry_failed_report_stage(
    state: Mapping[str, object],
) -> InvestigationState:
    """Safely retry only the failed review_report stage using preserved specialist outputs."""
    working_state: dict[str, object] = dict(state)
    if isinstance(working_state.get("result"), Mapping):
        res_copy = _clear_stage_provider_failure(
            dict(working_state["result"]),
            stage="review_report",
        )
        # Remove previous 'Review & Report generation is temporarily unavailable' limitation
        lims = res_copy.get("limitations")
        if isinstance(lims, list):
            res_copy["limitations"] = [
                lim
                for lim in lims
                if "Review & Report generation is temporarily unavailable" not in str(lim)
            ]
        res_copy["review_report"] = None
        res_copy["review_report_status"] = "pending"
        working_state["result"] = res_copy
    working_state["review_report"] = None
    working_state["review_report_status"] = "pending"
    update = run_review_report(working_state)  # type: ignore[arg-type]
    working_state.update(update)
    return working_state  # type: ignore[return-value]


def run_investigation(
    *,
    session: Session,
    employee_id: UUID,
    claim_id: UUID,
    task: str,
    repair_estimate_document_id: UUID | None = None,
    on_progress: Callable[[str, InvestigationState], None] | None = None,
    resume_state: Mapping[str, object] | None = None,
) -> InvestigationState:
    """Run one investigation with trusted database session context."""

    initial_state: InvestigationState = {
        "employee_id": str(employee_id),
        "claim_id": str(claim_id),
        "task": task,
        "claim_facts": None,
        "policy_evidence": [],
        "policy_retrieval_status": None,
        "policy_analysis": None,
        "policy_analysis_status": None,
        "claim_evidence": [],
        "claim_evidence_retrieval_status": None,
        "intake_analysis": None,
        "intake_analysis_status": None,
        "evidence_analysis": None,
        "evidence_analysis_status": None,
        "repair_estimate_document_id": (
            str(repair_estimate_document_id)
            if repair_estimate_document_id is not None
            else None
        ),
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": None,
        "repair_estimate_evidence": [],
        "risk_analysis": None,
        "risk_analysis_status": None,
        "selected_analysts": [],
        "supervisor_plan": None,
        "supervisor_status": None,
        "ai_analysis_status": None,
        "review_report": None,
        "review_report_status": "pending",
        "result": None,
        "error": None,
    }

    if isinstance(resume_state, Mapping) and isinstance(
        resume_state.get("result"), Mapping
    ):
        for key in initial_state:
            if key in {"employee_id", "claim_id", "task"}:
                continue
            if key in resume_state and resume_state[key] is not None:
                initial_state[key] = resume_state[key]  # type: ignore[literal-required]
        if initial_state.get("review_report_status") in {
            "unavailable",
            "failed",
            "pending",
            None,
        }:
            initial_state["review_report"] = None
            initial_state["review_report_status"] = "pending"
            if isinstance(initial_state.get("result"), Mapping):
                res_copy = _clear_stage_provider_failure(
                    dict(initial_state["result"]),
                    stage="review_report",
                )
                lims = res_copy.get("limitations")
                if isinstance(lims, list):
                    res_copy["limitations"] = [
                        lim
                        for lim in lims
                        if "Review & Report generation is temporarily unavailable"
                        not in str(lim)
                    ]
                initial_state["result"] = res_copy

    graph = build_investigation_graph()
    current_state: InvestigationState = initial_state.copy()
    for update in graph.stream(
        initial_state,
        context={"session": session},
        stream_mode="updates",
    ):
        for node_name, node_update in update.items():
            if not isinstance(node_update, dict):
                continue
            current_state.update(node_update)
            if on_progress is not None:
                on_progress(node_name, current_state.copy())

    return current_state
