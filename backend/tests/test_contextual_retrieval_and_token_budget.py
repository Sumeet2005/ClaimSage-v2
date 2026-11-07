"""Tests for agent-specific contextual retrieval, token budgeting, and observability."""

from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, Field

from claimsage.agents.token_budget_manager import (
    TokenBudgetAllocation,
    TokenBudgetManager,
    TokenBudgetUsage,
    get_token_budget_manager,
)
from claimsage.rag.contextual_retrieval import (
    ContextualPassage,
    ContextualRetrievalService,
    classify_document_type,
    eliminate_duplicate_passages,
)


class DummySchema(BaseModel):
    summary: str = Field(description="Summary of the analysis")
    findings: list[str] = Field(default_factory=list)


def test_token_budget_manager_allocations_and_effective_budget():
    mgr = TokenBudgetManager(
        budgets={"intake_agent": 2500, "policy_analyst": 2000},
        safety_margin_ratio=0.10,
    )
    alloc_intake = mgr.get_allocation("intake_agent")
    assert alloc_intake.max_input_tokens == 2500
    assert alloc_intake.effective_input_budget == 2250  # 2500 - 250 margin

    alloc_policy = mgr.get_allocation("policy_analyst")
    assert alloc_policy.max_input_tokens == 2000
    assert alloc_policy.effective_input_budget == 1800  # 2000 - 200 margin

    # Default fallback
    alloc_unknown = mgr.get_allocation("custom_stage")
    assert alloc_unknown.max_input_tokens == 2500


def test_token_budget_manager_counts_tokens_for_messages_and_schema():
    mgr = TokenBudgetManager()
    messages = [
        ("system", "You are an AI claims investigator."),
        ("human", "Investigate claim CLM-001 with itemized billing of INR 4,500."),
    ]
    prompt_tokens, schema_tokens, total_bytes = mgr.count_request_tokens(
        messages=messages,
        output_schema=DummySchema,
    )
    assert prompt_tokens > 0
    assert schema_tokens > 0
    assert total_bytes > 0


def test_fit_passages_to_budget_preserves_mandatory_and_ranks_by_relevance():
    mgr = TokenBudgetManager(
        budgets={"test_stage": 1000},
        safety_margin_ratio=0.10,
    )
    # Effective budget: 900 tokens.
    # Base prompt + schema: 400 tokens -> 500 available tokens.

    claim_id = uuid4()
    p_mand = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=uuid4(),
        chunk_id=uuid4(),
        filename="health_claim1_itemized_bill.pdf",
        document_type="hospital_bill",
        page_number=1,
        chunk_index=0,
        text="Itemized room rent charges INR 4,500 per day for 3 days.",
        relevance_score=0.70,
        source_type="claim_evidence",
        is_mandatory=True,
    )
    p_high = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=uuid4(),
        chunk_id=uuid4(),
        filename="discharge_summary.pdf",
        document_type="discharge_summary",
        page_number=1,
        chunk_index=0,
        text="Patient admitted on 2026-01-10 and discharged on 2026-01-13.",
        relevance_score=0.95,
        source_type="claim_evidence",
        is_mandatory=False,
    )
    p_low = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=uuid4(),
        chunk_id=uuid4(),
        filename="general_note.pdf",
        document_type="general_evidence",
        page_number=2,
        chunk_index=1,
        text="General administrative hospital note with minimal relevance. " * 30,
        relevance_score=0.30,
        source_type="claim_evidence",
        is_mandatory=False,
    )

    selected, omitted, stats = mgr.fit_passages_to_budget(
        [p_low, p_mand, p_high],
        stage="test_stage",
        base_prompt_tokens=300,
        schema_tokens=100,
        text_accessor=lambda p: p.text,
        id_accessor=lambda p: str(p.chunk_id),
        mandatory_predicate=lambda p: p.is_mandatory,
        score_accessor=lambda p: p.relevance_score,
    )

    # Mandatory passage must be in selected
    assert p_mand in selected
    # High relevance passage must be prioritized over low relevance
    assert p_high in selected
    assert stats["selected_count"] >= 2
    assert stats["safety_margin_tokens"] == 100


def test_classify_document_type_patterns():
    assert classify_document_type("health_claim1_itemized_bill.pdf") == "hospital_bill"
    assert classify_document_type("discharge_summary.pdf") == "discharge_summary"
    assert classify_document_type("treating_physician_note.pdf") == "physician_note"
    assert classify_document_type("surgeon_prescription.pdf") == "prescription"
    assert classify_document_type("mri_diagnostic_report.pdf") == "diagnostic_report"
    assert classify_document_type("garage_repair_estimate.pdf") == "repair_estimate"
    assert classify_document_type("police_fir_incident.pdf") == "incident_report"
    assert classify_document_type("pan_card_kyc.pdf") == "identity_document"
    assert classify_document_type("health_policy_v3.pdf") == "policy_clause"


def test_eliminate_duplicate_passages_removes_identical_chunks():
    cid1 = uuid4()
    cid2 = uuid4()
    did = uuid4()
    claim_id = uuid4()

    p1 = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=did,
        chunk_id=cid1,
        filename="doc.pdf",
        document_type="claim_evidence",
        page_number=1,
        chunk_index=0,
        text="Identical passage text content across chunks.",
        relevance_score=0.9,
        source_type="claim_evidence",
    )
    p2_same_id = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=did,
        chunk_id=cid1,  # Duplicate chunk_id
        filename="doc.pdf",
        document_type="claim_evidence",
        page_number=1,
        chunk_index=0,
        text="Different text with same chunk_id",
        relevance_score=0.8,
        source_type="claim_evidence",
    )
    p3_same_content = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=did,
        chunk_id=cid2,  # Different chunk_id
        filename="doc_copy.pdf",
        document_type="claim_evidence",
        page_number=2,
        chunk_index=1,
        text="   identical passage text  content across chunks.   ",  # Normalized duplicate
        relevance_score=0.85,
        source_type="claim_evidence",
    )
    p4_unique = ContextualPassage(
        claim_id=claim_id,
        policy_id=None,
        document_id=did,
        chunk_id=uuid4(),
        filename="unique.pdf",
        document_type="claim_evidence",
        page_number=1,
        chunk_index=0,
        text="Unique distinct passage content.",
        relevance_score=0.75,
        source_type="claim_evidence",
    )

    unique, removed_count = eliminate_duplicate_passages([p1, p2_same_id, p3_same_content, p4_unique])
    assert len(unique) == 2
    assert removed_count == 2
    assert unique[0].chunk_id == cid1
    assert unique[1].text == "Unique distinct passage content."


def test_contextual_passage_evidence_dict_formatting():
    claim_id = uuid4()
    did = uuid4()
    cid = uuid4()
    passage = ContextualPassage(
        claim_id=claim_id,
        policy_id=did,
        document_id=did,
        chunk_id=cid,
        filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
        document_type="policy_clause",
        page_number=3,
        chunk_index=1,
        text="Section 3 Room rent sub-limit INR 5,000 per day.",
        relevance_score=0.92,
        source_type="policy_evidence",
        clause_identifier="Section 3",
        clause_category="room_rent",
        metadata={"policy_version": "v3", "insurer_name": "Demo Assurance Co."},
    )
    ed = passage.to_evidence_dict()
    assert ed["chunk_id"] == str(cid)
    assert ed["document_id"] == str(did)
    assert ed["clause_identifier"] == "Section 3"
    assert ed["clause_category"] == "room_rent"
    assert ed["policy_version"] == "v3"
    assert ed["source_type"] == "policy_evidence"


def test_token_budget_usage_serialization():
    usage = TokenBudgetUsage(
        stage="evidence_analysis",
        model="openai/gpt-oss-120b",
        provider="groq",
        prompt_tokens=1800,
        schema_tokens=500,
        total_estimated_tokens=2300,
        budget_limit=2600,
        candidate_passages=8,
        selected_passages=5,
        omitted_passages=3,
        deduplicated_passages=1,
        execution_duration_seconds=1.2456,
    )
    d = usage.to_dict()
    assert d["stage"] == "evidence_analysis"
    assert d["total_estimated_tokens"] == 2300
    assert d["execution_duration_seconds"] == 1.246
    assert d["selected_passages"] == 5
    assert d["omitted_passages"] == 3
