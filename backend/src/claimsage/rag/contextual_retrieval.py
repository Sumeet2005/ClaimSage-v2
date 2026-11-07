"""Centralized contextual retrieval with agent-specific strategies and token budgeting."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.agents.token_budget_manager import (
    TokenBudgetManager,
    get_token_budget_manager,
)
from claimsage.db.models import ClaimEvidenceChunk, ClaimEvidenceDocument
from claimsage.rag.evidence_retrieval_service import (
    RetrievedEvidenceChunk,
    search_claim_evidence,
)
from claimsage.rag.retrieval_service import (
    RetrievedPolicyChunk,
    has_applicable_policy_documents,
    search_policy_chunks,
)
from claimsage.services.claim_access import get_authorized_claim

logger = logging.getLogger(__name__)

DocumentType = Literal[
    "hospital_bill",
    "discharge_summary",
    "physician_note",
    "prescription",
    "diagnostic_report",
    "repair_estimate",
    "incident_report",
    "identity_document",
    "policy_clause",
    "claim_evidence",
    "supporting_evidence",
]


@dataclass(frozen=True, slots=True)
class ContextualPassage:
    """A retrieved passage enriched with complete provenance and document classification."""

    claim_id: UUID
    policy_id: UUID | None
    document_id: UUID
    chunk_id: UUID
    filename: str
    document_type: str
    page_number: int
    chunk_index: int
    text: str
    relevance_score: float
    source_type: Literal["claim_evidence", "policy_evidence"]
    clause_identifier: str | None = None
    clause_category: str | None = None
    is_mandatory: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_evidence_dict(self) -> dict[str, Any]:
        """Convert to standard dictionary format expected by specialist agents."""
        res: dict[str, Any] = {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "filename": self.filename,
            "document_type": self.document_type,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "similarity": round(self.relevance_score, 4),
            "source_type": self.source_type,
        }
        if self.clause_identifier is not None:
            res["clause_identifier"] = self.clause_identifier
        if self.clause_category is not None:
            res["clause_category"] = self.clause_category
        if self.policy_id is not None:
            res["policy_id"] = str(self.policy_id)
        if self.metadata:
            res.update(self.metadata)
        return res


def classify_document_type(filename: str, text: str = "") -> str:
    """Classify document type using filename patterns and text cues."""
    fn = filename.lower()
    txt = text.lower()

    if any(k in fn for k in ("bill", "invoice", "itemized", "tariff", "receipt")):
        return "hospital_bill"
    if any(k in fn for k in ("discharge", "summary", "hospitalization")):
        return "discharge_summary"
    if any(k in fn for k in ("physician", "doctor", "clinical", "treating", "consultation")):
        return "physician_note"
    if any(k in fn for k in ("prescription", "rx", "medication", "pharma")):
        return "prescription"
    if any(k in fn for k in ("diagnostic", "lab", "pathology", "radiology", "mri", "xray", "ct_scan")):
        return "diagnostic_report"
    if any(k in fn for k in ("repair", "estimate", "garage", "workshop", "bodyshop")):
        return "repair_estimate"
    if any(k in fn for k in ("fir", "police", "incident", "accident")):
        return "incident_report"
    if any(k in fn for k in ("aadhaar", "pan", "passport", "license", "kyc")):
        return "identity_document"
    if "policy" in fn:
        return "policy_clause"

    # Fallback to text indicators
    if "itemized" in txt or ("room" in txt and "charges" in txt):
        return "hospital_bill"
    if "discharge" in txt and "admission" in txt:
        return "discharge_summary"
    if "physician" in txt or "treating doctor" in txt:
        return "physician_note"
    if "prescription" in txt or "rx" in txt:
        return "prescription"
    if "repair" in txt and ("labour" in txt or "parts" in txt):
        return "repair_estimate"

    return "claim_evidence"


def _normalize_text_for_dedup(text: str) -> str:
    """Normalize text whitespace and lowercase for deterministic duplicate detection."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def eliminate_duplicate_passages(
    passages: list[ContextualPassage],
) -> tuple[list[ContextualPassage], int]:
    """Eliminate duplicate passages by chunk ID and normalized text content hash."""
    seen_chunk_ids: set[UUID] = set()
    seen_content_hashes: set[str] = set()
    unique_passages: list[ContextualPassage] = []
    duplicates_removed = 0

    for p in passages:
        if p.chunk_id in seen_chunk_ids:
            duplicates_removed += 1
            continue

        norm_text = _normalize_text_for_dedup(p.text)
        content_hash = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()
        if content_hash in seen_content_hashes:
            duplicates_removed += 1
            continue

        seen_chunk_ids.add(p.chunk_id)
        seen_content_hashes.add(content_hash)
        unique_passages.append(p)

    return unique_passages, duplicates_removed


@dataclass(slots=True)
class ContextualRetrievalResult:
    """The result of contextual retrieval for an agent."""

    passages: list[ContextualPassage]
    omitted_passages: list[ContextualPassage]
    strategy: str
    candidate_count: int
    selected_count: int
    deduplicated_count: int
    omitted_count: int
    second_pass_performed: bool
    second_pass_passages_added: int
    estimated_input_tokens: int
    budget_stats: dict[str, Any]

    def to_evidence_dicts(self) -> list[dict[str, Any]]:
        return [p.to_evidence_dict() for p in self.passages]


class ContextualRetrievalService:
    """Centralized retrieval service supporting agent-specific strategies and token budgets."""

    def __init__(
        self,
        token_budget_manager: TokenBudgetManager | None = None,
    ) -> None:
        self.budget_manager = token_budget_manager or get_token_budget_manager()

    def retrieve_for_agent(
        self,
        db: Session,
        *,
        employee_id: UUID,
        claim_id: UUID,
        stage: str,
        task: str,
        claim_type: str,
        top_k: int = 5,
        min_similarity: float = 0.20,
        base_prompt_tokens: int = 400,
        schema_tokens: int = 300,
        existing_claim_evidence: list[dict[str, Any]] | None = None,
        existing_policy_evidence: list[dict[str, Any]] | None = None,
        filter_document_types: list[str] | None = None,
    ) -> ContextualRetrievalResult:
        """Execute agent-specific contextual retrieval with token budget management."""
        candidates: list[ContextualPassage] = []
        second_pass_performed = False
        second_pass_added = 0

        # Authorize claim
        claim = get_authorized_claim(db, employee_id=employee_id, claim_id=claim_id)

        # -------------------------------------------------------------
        # 1. Base Retrieval according to Stage Strategy
        # -------------------------------------------------------------
        if stage == "policy_analyst":
            candidates = self._retrieve_policy_candidates(
                db,
                employee_id=employee_id,
                claim_id=claim_id,
                task=task,
                claim_type=claim_type,
                top_k=top_k,
                min_similarity=min_similarity,
                existing_policy_evidence=existing_policy_evidence,
            )
            # Second-pass check for policy clauses
            second_pass_candidates = self._policy_second_pass(
                db,
                employee_id=employee_id,
                claim_id=claim_id,
                claim_type=claim_type,
                current_candidates=candidates,
            )
            if second_pass_candidates:
                second_pass_performed = True
                second_pass_added = len(second_pass_candidates)
                candidates.extend(second_pass_candidates)

        elif stage in {"intake_agent", "evidence_analyst", "risk_anomaly_agent", "repair_estimate_analyst"}:
            candidates = self._retrieve_claim_candidates(
                db,
                employee_id=employee_id,
                claim_id=claim_id,
                task=task,
                stage=stage,
                claim_type=claim_type,
                top_k=top_k,
                min_similarity=min_similarity,
                existing_claim_evidence=existing_claim_evidence,
                filter_document_types=filter_document_types,
            )
            # Second-pass check for critical claim documents
            if stage in {"evidence_analyst", "risk_anomaly_agent"}:
                second_pass_candidates = self._claim_second_pass(
                    db,
                    employee_id=employee_id,
                    claim_id=claim_id,
                    claim_type=claim_type,
                    current_candidates=candidates,
                )
                if second_pass_candidates:
                    second_pass_performed = True
                    second_pass_added = len(second_pass_candidates)
                    candidates.extend(second_pass_candidates)

        # -------------------------------------------------------------
        # 2. Duplicate Chunk Elimination
        # -------------------------------------------------------------
        candidate_count = len(candidates)
        unique_passages, deduplicated_count = eliminate_duplicate_passages(candidates)

        # -------------------------------------------------------------
        # 3. Token-Budget Enforcement
        # -------------------------------------------------------------
        selected, omitted, budget_stats = self.budget_manager.fit_passages_to_budget(
            unique_passages,
            stage=stage,
            base_prompt_tokens=base_prompt_tokens,
            schema_tokens=schema_tokens,
            text_accessor=lambda p: p.text,
            id_accessor=lambda p: str(p.chunk_id),
            mandatory_predicate=lambda p: p.is_mandatory,
            score_accessor=lambda p: p.relevance_score,
        )

        return ContextualRetrievalResult(
            passages=selected,
            omitted_passages=omitted,
            strategy=f"{stage}_contextual",
            candidate_count=candidate_count,
            selected_count=len(selected),
            deduplicated_count=deduplicated_count,
            omitted_count=len(omitted),
            second_pass_performed=second_pass_performed,
            second_pass_passages_added=second_pass_added,
            estimated_input_tokens=budget_stats.get("total_estimated_tokens", 0),
            budget_stats=budget_stats,
        )

    def _retrieve_claim_candidates(
        self,
        db: Session,
        *,
        employee_id: UUID,
        claim_id: UUID,
        task: str,
        stage: str,
        claim_type: str,
        top_k: int,
        min_similarity: float,
        existing_claim_evidence: list[dict[str, Any]] | None,
        filter_document_types: list[str] | None,
    ) -> list[ContextualPassage]:
        """Retrieve and wrap claim evidence chunks into ContextualPassages."""
        raw_chunks: list[RetrievedEvidenceChunk] = []

        if existing_claim_evidence:
            # Wrap existing graph claim evidence if already retrieved
            passages: list[ContextualPassage] = []
            for item in existing_claim_evidence:
                cid = UUID(str(item["chunk_id"]))
                did = UUID(str(item["document_id"]))
                fn = str(item.get("filename", ""))
                txt = str(item.get("text", ""))
                doc_type = classify_document_type(fn, txt)
                if filter_document_types and doc_type not in filter_document_types:
                    continue
                score = float(item.get("similarity", 0.8) or 0.8)
                is_mand = "itemized" in fn.lower() or "discharge" in fn.lower()
                passages.append(
                    ContextualPassage(
                        claim_id=claim_id,
                        policy_id=None,
                        document_id=did,
                        chunk_id=cid,
                        filename=fn,
                        document_type=doc_type,
                        page_number=int(item.get("page_number", 1)),
                        chunk_index=int(item.get("chunk_index", 0)),
                        text=txt,
                        relevance_score=score,
                        source_type="claim_evidence",
                        is_mandatory=is_mand,
                        metadata={
                            "extraction_method": item.get("extraction_method", "native"),
                            "ocr_confidence": item.get("ocr_confidence"),
                        },
                    )
                )
            return passages

        try:
            # Query-tailoring by stage
            query = task
            if stage == "repair_estimate_analyst":
                query = f"repair estimate vehicle damage labour parts workshop {task}"
            elif stage == "intake_agent":
                query = f"claim details patient vehicle dates policy amount {task}"

            raw_chunks = search_claim_evidence(
                db,
                employee_id=employee_id,
                claim_id=claim_id,
                query=query,
                top_k=max(top_k, 5),
                min_similarity=min_similarity,
            )
        except Exception as exc:
            logger.warning("Claim evidence search failed: %s", exc)
            return []

        passages = []
        for chunk in raw_chunks:
            doc_type = classify_document_type(chunk.filename, chunk.text)
            if filter_document_types and doc_type not in filter_document_types:
                continue
            is_mand = "itemized" in chunk.filename.lower() or "discharge" in chunk.filename.lower()
            passages.append(
                ContextualPassage(
                    claim_id=claim_id,
                    policy_id=None,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    filename=chunk.filename,
                    document_type=doc_type,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    relevance_score=chunk.similarity or 0.5,
                    source_type="claim_evidence",
                    is_mandatory=is_mand,
                    metadata={
                        "embedding_model": chunk.embedding_model,
                        "extraction_method": chunk.extraction_method,
                        "ocr_confidence": chunk.ocr_confidence,
                    },
                )
            )
        return passages

    def _retrieve_policy_candidates(
        self,
        db: Session,
        *,
        employee_id: UUID,
        claim_id: UUID,
        task: str,
        claim_type: str,
        top_k: int,
        min_similarity: float,
        existing_policy_evidence: list[dict[str, Any]] | None,
    ) -> list[ContextualPassage]:
        """Retrieve and wrap policy chunks into ContextualPassages."""
        if existing_policy_evidence:
            passages: list[ContextualPassage] = []
            for item in existing_policy_evidence:
                cid = UUID(str(item["chunk_id"]))
                did = UUID(str(item["document_id"]))
                fn = str(item.get("filename", ""))
                txt = str(item.get("text", ""))
                score = float(item.get("similarity", 0.8) or 0.8)
                c_ident = item.get("clause_identifier")
                c_cat = item.get("clause_category")
                is_mand = "room rent" in txt.lower() or "sub-limit" in txt.lower()
                passages.append(
                    ContextualPassage(
                        claim_id=claim_id,
                        policy_id=did,
                        document_id=did,
                        chunk_id=cid,
                        filename=fn,
                        document_type="policy_clause",
                        page_number=int(item.get("page_number", 1)),
                        chunk_index=int(item.get("chunk_index", 0)),
                        text=txt,
                        relevance_score=score,
                        source_type="policy_evidence",
                        clause_identifier=str(c_ident) if c_ident else None,
                        clause_category=str(c_cat) if c_cat else None,
                        is_mandatory=is_mand,
                        metadata={
                            "insurer_name": item.get("insurer_name"),
                            "product_name": item.get("product_name"),
                            "policy_identifier": item.get("policy_identifier"),
                            "policy_version": item.get("policy_version"),
                            "source_url": item.get("source_url"),
                            "clause_id": item.get("clause_id"),
                        },
                    )
                )
            return passages

        try:
            if not has_applicable_policy_documents(db, employee_id=employee_id, claim_id=claim_id):
                return []

            raw_chunks = search_policy_chunks(
                db,
                employee_id=employee_id,
                claim_id=claim_id,
                query=task,
                top_k=top_k,
                min_similarity=min_similarity,
            )
        except Exception as exc:
            logger.warning("Policy search failed: %s", exc)
            return []

        passages = []
        for chunk in raw_chunks:
            is_mand = "room rent" in chunk.text.lower() or "sub-limit" in chunk.text.lower()
            passages.append(
                ContextualPassage(
                    claim_id=claim_id,
                    policy_id=chunk.document_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    filename=chunk.filename,
                    document_type="policy_clause",
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    relevance_score=chunk.similarity,
                    source_type="policy_evidence",
                    clause_identifier=chunk.clause_identifier,
                    clause_category=chunk.clause_category,
                    is_mandatory=is_mand,
                    metadata={
                        "insurer_name": chunk.insurer_name,
                        "product_name": chunk.product_name,
                        "policy_identifier": getattr(chunk, "policy_identifier", None),
                        "policy_version": chunk.policy_version,
                        "source_url": chunk.source_url,
                        "clause_id": str(chunk.clause_id) if chunk.clause_id else None,
                    },
                )
            )
        return passages

    def _claim_second_pass(
        self,
        db: Session,
        *,
        employee_id: UUID,
        claim_id: UUID,
        claim_type: str,
        current_candidates: list[ContextualPassage],
    ) -> list[ContextualPassage]:
        """Perform second-pass retrieval for essential missing claim document types."""
        present_types = {p.document_type for p in current_candidates}
        second_pass_chunks: list[ContextualPassage] = []

        # For health claims, both hospital_bill and discharge_summary are critical
        critical_types = ["hospital_bill", "discharge_summary"] if claim_type == "health" else ["repair_estimate"]
        missing_types = [t for t in critical_types if t not in present_types]

        if not missing_types:
            return []

        for m_type in missing_types:
            q = (
                "itemized hospital billing room rent nursing charges invoice"
                if m_type == "hospital_bill"
                else "hospital discharge summary diagnosis admission date treatment"
                if m_type == "discharge_summary"
                else "motor vehicle repair estimate garage invoice parts labour"
            )
            try:
                extra_chunks = search_claim_evidence(
                    db,
                    employee_id=employee_id,
                    claim_id=claim_id,
                    query=q,
                    top_k=2,
                    min_similarity=0.15,
                )
                for chunk in extra_chunks:
                    doc_type = classify_document_type(chunk.filename, chunk.text)
                    if doc_type == m_type or m_type in chunk.filename.lower():
                        second_pass_chunks.append(
                            ContextualPassage(
                                claim_id=claim_id,
                                policy_id=None,
                                document_id=chunk.document_id,
                                chunk_id=chunk.chunk_id,
                                filename=chunk.filename,
                                document_type=doc_type,
                                page_number=chunk.page_number,
                                chunk_index=chunk.chunk_index,
                                text=chunk.text,
                                relevance_score=chunk.similarity or 0.6,
                                source_type="claim_evidence",
                                is_mandatory=True,
                                metadata={
                                    "extraction_method": chunk.extraction_method,
                                    "second_pass": True,
                                },
                            )
                        )
            except Exception as e:
                logger.debug("Second pass for %s skipped: %s", m_type, e)

        return second_pass_chunks

    def _policy_second_pass(
        self,
        db: Session,
        *,
        employee_id: UUID,
        claim_id: UUID,
        claim_type: str,
        current_candidates: list[ContextualPassage],
    ) -> list[ContextualPassage]:
        """Perform second-pass policy retrieval for specific critical sub-limits."""
        has_room_rent = any(
            "room rent" in p.text.lower() or "5,000" in p.text
            for p in current_candidates
        )
        if claim_type == "health" and not has_room_rent:
            try:
                extra = search_policy_chunks(
                    db,
                    employee_id=employee_id,
                    claim_id=claim_id,
                    query="Section 3 Room rent sub-limit INR 5000 per day ICU charges",
                    top_k=2,
                    min_similarity=0.15,
                )
                second_pass: list[ContextualPassage] = []
                for chunk in extra:
                    if "room" in chunk.text.lower() or "5,000" in chunk.text:
                        second_pass.append(
                            ContextualPassage(
                                claim_id=claim_id,
                                policy_id=chunk.document_id,
                                document_id=chunk.document_id,
                                chunk_id=chunk.chunk_id,
                                filename=chunk.filename,
                                document_type="policy_clause",
                                page_number=chunk.page_number,
                                chunk_index=chunk.chunk_index,
                                text=chunk.text,
                                relevance_score=chunk.similarity,
                                source_type="policy_evidence",
                                clause_identifier=chunk.clause_identifier,
                                clause_category=chunk.clause_category,
                                is_mandatory=True,
                                metadata={
                                    "policy_version": chunk.policy_version,
                                    "second_pass": True,
                                },
                            )
                        )
                return second_pass
            except Exception as e:
                logger.debug("Policy second pass skipped: %s", e)
        return []


# Global singleton instance
_contextual_service: ContextualRetrievalService | None = None


def get_contextual_retrieval_service() -> ContextualRetrievalService:
    """Return the global ContextualRetrievalService instance."""
    global _contextual_service
    if _contextual_service is None:
        _contextual_service = ContextualRetrievalService()
    return _contextual_service
