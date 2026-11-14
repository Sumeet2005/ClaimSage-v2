"""Comprehensive regression tests for Investigation Reliability and Duplicate Evidence Remediation.

Tests verify:
1. Evidence deduplication & document diversity in semantic retrieval.
2. Policy Analyst quote validation robustness & whitespace/punctuation normalization.
3. Risk & Anomaly Agent token-bounded compaction & specialist summary bounds.
4. Review & Report Agent token compaction & fallback partial report synthesis.
5. Specialist applicability (Repair Estimate Analyst skipped for health claims).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from sqlalchemy import delete

from claimsage.agents.graph import (
    build_investigation_graph,
    run_repair_estimate_analyst,
    run_review_report,
)
from claimsage.agents.policy_analyst import (
    PolicyAnalystError,
    analyze_policy,
)
from claimsage.agents.review_report_agent import (
    _build_compact_model_payload,
    analyze_review_report,
    build_fallback_partial_report,
)
from claimsage.agents.risk_anomaly_agent import (
    _build_compact_analyst_summaries,
    _build_compact_risk_payload,
    analyze_risk_and_anomalies,
)
from claimsage.agents.schemas import (
    EvidenceAnalystOutput,
    IntakeDocumentOutput,
    PolicyAnalystOutput,
    PolicyClauseFinding,
    PolicyDerivedConclusion,
    ReviewReportEvidenceChunk,
    ReviewReportEvidenceQuote,
    ReviewReportInput,
    ReviewReportOutput,
    ReviewReportSpecialistInput,
    RiskAnomalyEvidenceQuote,
    RiskAnomalyExtraction,
    RiskAnomalyFindingExtraction,
    RiskAnomalyOutput,
)
from claimsage.db.models import (
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
    EmployeeRole,
)
from claimsage.db.session import SessionLocal
from claimsage.rag import evidence_retrieval_service
from claimsage.rag.evidence_retrieval_service import (
    RetrievedEvidenceChunk,
    search_claim_evidence,
)

TEST_MODEL = "test-remediation-model"
BASE_VECTOR = [1.0] + [0.0] * 383
CLOSE_VECTOR = [0.99] + [0.0] * 383


class DeterministicEmbeddingService:
    model_name = TEST_MODEL

    def embed_query(self, query: str) -> list[float]:
        return BASE_VECTOR


# ---------------------------------------------------------------------------
# 1. Evidence Retrieval Deduplication and Diversity
# ---------------------------------------------------------------------------

@pytest.fixture
def multi_doc_retrieval_scenario(monkeypatch):
    """Seed multiple documents with multiple chunks into claimsage_test."""
    emp_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()

    emp = Employee(
        id=emp_id,
        email=f"remediation-{emp_id}@test.local",
        display_name="Remediation Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"team-{emp_id}",
    )
    claim = Claim(
        id=claim_id,
        claim_number=f"REM-{uuid.uuid4().hex[:10]}",
        claimant_name="Remediation Claimant",
        claim_type="health",
        assigned_employee_id=emp_id,
        team_id=emp.team_id,
        status="under_review",
    )
    doc1 = ClaimEvidenceDocument(
        id=doc1_id,
        claim_id=claim_id,
        filename="physician_note.pdf",
        checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        mime_type="application/pdf",
        file_size_bytes=2048,
        uploaded_by_employee_id=emp_id,
        status="processed",
    )
    doc2 = ClaimEvidenceDocument(
        id=doc2_id,
        claim_id=claim_id,
        filename="itemized_bill.pdf",
        checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        mime_type="application/pdf",
        file_size_bytes=3072,
        uploaded_by_employee_id=emp_id,
        status="processed",
    )

    # 3 chunks for doc1, 2 chunks for doc2
    chunks = [
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=doc1_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Physician note passage 1: patient symptoms and onset.",
            extraction_method="native",
            embedding=BASE_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=doc1_id,
            page_number=1,
            chunk_index=1,
            chunk_id=uuid.uuid4().hex,
            text="Physician note passage 2: clinical examination findings.",
            extraction_method="native",
            embedding=BASE_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=doc1_id,
            page_number=1,
            chunk_index=2,
            chunk_id=uuid.uuid4().hex,
            text="Physician note passage 3: prescription and orders.",
            extraction_method="native",
            embedding=BASE_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=doc2_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Itemized bill passage 1: surgery room charges.",
            extraction_method="native",
            embedding=CLOSE_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=doc2_id,
            page_number=1,
            chunk_index=1,
            chunk_id=uuid.uuid4().hex,
            text="Itemized bill passage 2: pharmacy and medication charges.",
            extraction_method="native",
            embedding=CLOSE_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
    ]

    with SessionLocal.begin() as db:
        db.add(emp)
        db.flush()
        db.add(claim)
        db.flush()
        db.add_all([doc1, doc2])
        db.flush()
        db.add_all(chunks)

    monkeypatch.setattr(
        evidence_retrieval_service,
        "get_embedding_service",
        lambda: DeterministicEmbeddingService(),
    )

    yield {
        "employee_id": emp_id,
        "claim_id": claim_id,
        "doc1_id": doc1_id,
        "doc2_id": doc2_id,
    }

    with SessionLocal.begin() as db:
        db.execute(delete(ClaimEvidenceChunk).where(ClaimEvidenceChunk.document_id.in_([doc1_id, doc2_id])))
        db.execute(delete(ClaimEvidenceDocument).where(ClaimEvidenceDocument.id.in_([doc1_id, doc2_id])))
        db.execute(delete(Claim).where(Claim.id == claim_id))
        db.execute(delete(Employee).where(Employee.id == emp_id))


def test_retrieval_balances_multiple_documents_and_deduplicates(multi_doc_retrieval_scenario):
    """Verify top_k retrieval does not let doc1 monopolize all slots when doc2 matches."""
    with SessionLocal() as db:
        results = search_claim_evidence(
            db,
            employee_id=multi_doc_retrieval_scenario["employee_id"],
            claim_id=multi_doc_retrieval_scenario["claim_id"],
            query="clinical and billing evidence",
            top_k=4,
        )

    assert len(results) == 4
    # All chunk_ids must be unique
    chunk_ids = [r.chunk_id for r in results]
    assert len(set(chunk_ids)) == len(chunk_ids)

    # Both documents must be represented in top_4
    doc_ids = {r.document_id for r in results}
    assert multi_doc_retrieval_scenario["doc1_id"] in doc_ids
    assert multi_doc_retrieval_scenario["doc2_id"] in doc_ids


# ---------------------------------------------------------------------------
# 2. Policy Analyst Robustness
# ---------------------------------------------------------------------------

def test_policy_analyst_accepts_empty_summary_and_assessment_quotes(monkeypatch):
    """Verify Policy Analyst does not fail when summary_quotes or assessment_quotes are empty."""
    mock_model = MagicMock()
    mock_structured = MagicMock()
    mock_model.with_structured_output.return_value = mock_structured

    fake_output = PolicyAnalystOutput(
        summary="Hospitalization clause applies to standard admissions.",
        summary_quotes=[],
        assessment_quotes=[],
        relevant_clauses=[
            PolicyClauseFinding(
                finding="Hospitalization is covered under Section 3.1.",
                supporting_evidence_ids=["chunk-001"],
                supporting_quotes=[{"evidence_id": "chunk-001", "quote": "Inpatient care is covered."}],
                explanation="Hospitalization clause explains coverage.",
                confidence="high",
            )
        ],
        coverage_indicators=[
            PolicyDerivedConclusion(
                conclusion="Inpatient hospitalization expenses are eligible.",
                supporting_evidence_ids=["chunk-001"],
                supporting_quotes=[{"evidence_id": "chunk-001", "quote": "Inpatient care is covered."}],
            )
        ],
        exclusions_and_conditions=[],
        missing_information=[],
        evidence_gaps=[],
        overall_assessment="potentially_supportive",
        human_review_required=True,
    )
    mock_structured.invoke.return_value = fake_output
    monkeypatch.setattr("claimsage.agents.policy_analyst.get_chat_model", lambda: mock_model)

    result = analyze_policy(
        task="Check hospitalization coverage",
        policy_evidence=[
            {
                "chunk_id": "chunk-001",
                "document_id": "doc-001",
                "filename": "policy.pdf",
                "page_number": 3,
                "text": "Inpatient care is covered.",
            }
        ],
    )

    assert result.overall_assessment == "potentially_supportive"
    assert len(result.relevant_clauses) == 1
    assert result.summary_quotes == []


def test_policy_analyst_normalizes_quotes_for_whitespace_and_punctuation(monkeypatch):
    """Verify quote matching succeeds despite curly quotes or minor whitespace variations."""
    mock_model = MagicMock()
    mock_structured = MagicMock()
    mock_model.with_structured_output.return_value = mock_structured

    # Quote uses curly quotes and normalized whitespace
    fake_output = PolicyAnalystOutput(
        summary="Clause review",
        summary_quotes=[],
        assessment_quotes=[],
        relevant_clauses=[
            PolicyClauseFinding(
                finding="Pre-existing conditions clause.",
                supporting_evidence_ids=["chunk-002"],
                supporting_quotes=[{"evidence_id": "chunk-002", "quote": '“Pre-existing” illness is excluded.'}],
                explanation="Pre-existing illness excluded.",
                confidence="high",
            )
        ],
        coverage_indicators=[],
        exclusions_and_conditions=[
            PolicyDerivedConclusion(
                conclusion="Pre-existing conditions excluded.",
                supporting_evidence_ids=["chunk-002"],
                supporting_quotes=[{"evidence_id": "chunk-002", "quote": '“Pre-existing” illness is excluded.'}],
            )
        ],
        missing_information=[],
        evidence_gaps=[],
        overall_assessment="potentially_restrictive",
        human_review_required=True,
    )
    mock_structured.invoke.return_value = fake_output
    monkeypatch.setattr("claimsage.agents.policy_analyst.get_chat_model", lambda: mock_model)

    # Source has straight quotes and double spaces
    result = analyze_policy(
        task="Check exclusion",
        policy_evidence=[
            {
                "chunk_id": "chunk-002",
                "document_id": "doc-001",
                "filename": "policy.pdf",
                "page_number": 4,
                "text": 'The  policy  states  "pre-existing" illness is excluded. Please review.',
            }
        ],
    )

    assert result.overall_assessment == "potentially_restrictive"


# ---------------------------------------------------------------------------
# 3. Risk & Anomaly Agent Compaction
# ---------------------------------------------------------------------------

def test_risk_anomaly_payload_compaction_bounds_size():
    """Verify _build_compact_risk_payload limits chunk count and truncates long text."""
    long_text = "Clinical observation note text. " * 50
    evidence = [
        {
            "chunk_id": f"chunk-{i}",
            "document_id": "doc-1",
            "filename": f"file_{i}.pdf",
            "page_number": 1,
            "text": long_text,
        }
        for i in range(8)
    ]

    payload = _build_compact_risk_payload(
        task="Investigate discrepancies",
        claim_facts={"claim_type": "health"},
        evidence_records=evidence,
        completed_analyst_outputs=None,
        max_chunks=4,
    )

    assert len(payload["claim_evidence"]) == 4
    for item in payload["claim_evidence"]:
        assert len(item["text"]) <= 850
        assert len(item["text"]) < len(long_text)


def test_risk_anomaly_summaries_bounds_specialist_arrays():
    """Verify _build_compact_analyst_summaries limits array sizes for token efficiency."""
    completed = {
        "intake_agent": {
            "summary": "Intake completed",
            "extracted_fields": [{"field_name": f"f_{i}", "value": f"v_{i}"} for i in range(12)],
            "document_inventory": [{"document_type": "note", "filename": f"d_{i}.pdf"} for i in range(10)],
        },
        "evidence_analyst": {
            "summary": "Evidence analyzed",
            "factual_findings": [{"finding": f"finding {i}"} for i in range(10)],
            "timeline": [{"event": f"event {i}"} for i in range(10)],
        },
    }

    compact = _build_compact_analyst_summaries(completed)
    assert len(compact["intake_agent"]["extracted_fields"]) <= 6
    assert len(compact["intake_agent"]["document_inventory"]) <= 5
    assert len(compact["evidence_analyst"]["factual_findings"]) <= 5
    assert len(compact["evidence_analyst"]["timeline"]) <= 5


# ---------------------------------------------------------------------------
# 4. Review Report Fallback Partial Report Synthesis
# ---------------------------------------------------------------------------

def test_build_fallback_partial_report_synthesizes_incomplete_report():
    """Verify build_fallback_partial_report builds an auditable partial report."""
    doc_id = uuid.uuid4()
    ev_chunk = ReviewReportEvidenceChunk(
        chunk_id="chk-001",
        document_id=doc_id,
        filename="discharge_summary.pdf",
        page_number=1,
        chunk_index=0,
        text="Patient was discharged on 2026-03-15 in stable condition.",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "claim_id": "test-claim"},
        retrieved_evidence=[ev_chunk],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis={"summary": "Intake completed"},
        ),
        evidence_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "summary": "Evidence analyzed",
                "factual_findings": [
                    {
                        "finding": "Patient discharged in stable condition.",
                        "explanation": "Documented on page 1 of discharge summary.",
                        "supporting_evidence_ids": ["chk-001"],
                        "supporting_quotes": [
                            {"evidence_id": "chk-001", "quote": "Patient was discharged on 2026-03-15 in stable condition."}
                        ],
                    }
                ],
            },
        ),
        policy_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="unavailable", analysis=None),
    )

    partial_report = build_fallback_partial_report(
        report_input=report_input,
        error_message="rate_limited: GroqTPMExceeded",
    )

    assert isinstance(partial_report, ReviewReportOutput)
    assert partial_report.overall_status == "incomplete"
    assert partial_report.human_review_required is True
    assert len(partial_report.observed_facts) == 1
    assert partial_report.observed_facts[0].statement == "Patient discharged in stable condition."
    assert partial_report.observed_facts[0].sources[0].filename == "discharge_summary.pdf"

    # Coverage verification
    coverage_by_spec = {c.specialist: c for c in partial_report.specialist_coverage}
    assert coverage_by_spec["evidence_analyst"].status == "completed"
    assert coverage_by_spec["policy_analyst"].status == "unavailable"
    assert coverage_by_spec["repair_estimate_analyst"].status == "skipped"


# ---------------------------------------------------------------------------
# 5. Specialist Applicability: Repair Estimate Skipped for Health
# ---------------------------------------------------------------------------

def test_repair_estimate_analyst_is_skipped_for_health_claims():
    """Verify repair estimate analyst returns skipped status for health claims."""
    state = {
        "claim_id": str(uuid.uuid4()),
        "employee_id": str(uuid.uuid4()),
        "task": "Investigate health claim",
        "selected_analysts": ["intake_agent", "evidence_analyst", "policy_analyst", "risk_anomaly_agent"],
        "repair_estimate_document_id": None,
        "result": {"task": "Investigate health claim"},
    }
    runtime = MagicMock()

    output = run_repair_estimate_analyst(state, runtime)
    assert output["repair_estimate_analysis"] is None
    assert output["repair_estimate_analysis_status"] == "skipped"


# ---------------------------------------------------------------------------
# 6. Critical Evidence Grounding & Policy Analyst State Transfer
# ---------------------------------------------------------------------------

def test_policy_analyst_receives_claim_evidence_and_grounds_findings(monkeypatch):
    """Verify Policy Analyst receives claim evidence and Evidence Analyst findings in prompt."""
    from claimsage.agents import policy_analyst
    import json

    captured_payload = {}

    def mock_invoke_structured(runnable, *, messages, output_schema, stage):
        nonlocal captured_payload
        for role, text in messages:
            if role == "human":
                captured_payload = json.loads(text)
        return PolicyAnalystOutput(
            summary="Room rent of INR 4,500/day is within the policy ceiling of INR 5,000/day.",
            relevant_clauses=[
                PolicyClauseFinding(
                    finding="Room rent limit of INR 5,000 per day applies to inpatient care.",
                    supporting_evidence_ids=["pol-chk-001"],
                    supporting_quotes=[
                        {"evidence_id": "pol-chk-001", "quote": "Room rent limit INR 5,000 per day."}
                    ],
                    explanation="Policy sets daily room rent cap.",
                    confidence="high",
                )
            ],
            coverage_indicators=[
                PolicyDerivedConclusion(
                    conclusion="Inpatient stay is covered up to room limit.",
                    supporting_evidence_ids=["pol-chk-001"],
                    supporting_quotes=[
                        {"evidence_id": "pol-chk-001", "quote": "Room rent limit INR 5,000 per day."}
                    ],
                )
            ],
            exclusions_and_conditions=[],
            missing_information=[],
            evidence_gaps=[],
            overall_assessment="potentially_supportive",
            human_review_required=True,
        )

    monkeypatch.setattr(policy_analyst, "invoke_structured", mock_invoke_structured)
    monkeypatch.setattr(policy_analyst, "get_chat_model", lambda: MagicMock())

    policy_ev = [
        {
            "chunk_id": "pol-chk-001",
            "text": "In-patient hospitalization. Room rent limit INR 5,000 per day.",
            "filename": "policy_v3.pdf",
            "page_number": 1,
        }
    ]
    claim_ev = [
        {
            "chunk_id": "claim-chk-bill",
            "document_id": "doc-bill-001",
            "filename": "health_claim1_itemized_bill.pdf",
            "page_number": 1,
            "text": "Room rent charge: INR 4,500 per day for 3 days.",
        },
        {
            "chunk_id": "claim-chk-note",
            "document_id": "doc-note-001",
            "filename": "physician_note.pdf",
            "page_number": 1,
            "text": "Patient admitted with acute appendicitis. Laparoscopic appendectomy performed.",
        },
    ]
    ea_analysis = {
        "summary": "Bill shows room charges of INR 4,500/day, below policy limit of INR 5,000/day.",
        "factual_findings": [
            {"finding": "Itemized bill specifies room rent of INR 4,500 per day."}
        ],
    }

    result = analyze_policy(
        task="Investigate health claim room rent compliance",
        policy_evidence=policy_ev,
        claim_evidence=claim_ev,
        evidence_analysis=ea_analysis,
    )

    assert isinstance(result, PolicyAnalystOutput)
    assert result.overall_assessment == "potentially_supportive"
    # Verify prompt payload contains claim evidence and evidence analyst findings
    assert "claim_evidence" in captured_payload
    assert len(captured_payload["claim_evidence"]) == 2
    assert captured_payload["claim_evidence"][0]["filename"] == "health_claim1_itemized_bill.pdf"
    assert "evidence_analyst_findings" in captured_payload
    assert "INR 4,500" in captured_payload["evidence_analyst_findings"]["summary"]


def test_unique_document_grouping_logic():
    """Verify multiple chunks from the same document group into one parent entry with nested passages."""
    raw_chunks = [
        {
            "chunk_id": "chk-p1",
            "document_id": "doc-physician-note",
            "filename": "physician_note.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Passage 1 content",
            "similarity": 0.88,
        },
        {
            "chunk_id": "chk-p2",
            "document_id": "doc-physician-note",
            "filename": "physician_note.pdf",
            "page_number": 1,
            "chunk_index": 1,
            "text": "Passage 2 content",
            "similarity": 0.82,
        },
        {
            "chunk_id": "chk-p3",
            "document_id": "doc-physician-note",
            "filename": "physician_note.pdf",
            "page_number": 1,
            "chunk_index": 2,
            "text": "Passage 3 content",
            "similarity": 0.79,
        },
        {
            "chunk_id": "chk-bill",
            "document_id": "doc-bill",
            "filename": "itemized_bill.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Bill content",
            "similarity": 0.91,
        },
    ]

    # Grouping algorithm matching frontend implementation
    doc_map = {}
    for chunk in raw_chunks:
        doc_id = chunk["document_id"]
        if doc_id not in doc_map:
            doc_map[doc_id] = {
                "document_id": doc_id,
                "filename": chunk["filename"],
                "passages": [],
            }
        doc_map[doc_id]["passages"].append(chunk)

    grouped_docs = list(doc_map.values())

    # Exactly 2 parent document cards, NOT 4 separate cards
    assert len(grouped_docs) == 2
    physician_doc = next(d for d in grouped_docs if d["document_id"] == "doc-physician-note")
    assert physician_doc["filename"] == "physician_note.pdf"
    # All 3 passages preserved underneath the single document card
    assert len(physician_doc["passages"]) == 3
    assert physician_doc["passages"][0]["chunk_id"] == "chk-p1"
    assert physician_doc["passages"][1]["chunk_id"] == "chk-p2"
    assert physician_doc["passages"][2]["chunk_id"] == "chk-p3"


# ---------------------------------------------------------------------------
# 7. Risk Agent Recovery & Provider Error Handling
# ---------------------------------------------------------------------------

def test_tool_use_failed_is_retryable_and_classified_as_malformed_response():
    """Verify tool_use_failed maps to malformed_response and triggers retry."""
    from claimsage.agents.llm import _is_retryable, provider_failure_category

    err = RuntimeError("Groq tool error")
    err.status_code = 400
    err.code = "tool_use_failed"

    assert provider_failure_category(err) == "malformed_response"
    assert _is_retryable(err) is True


def test_review_report_and_fallback_accepts_quotes_with_ellipses():
    """Verify Review Report validator and fallback builder accept quotes with ellipses."""
    from claimsage.agents.review_report_agent import (
        _validate_input,
        build_fallback_partial_report,
    )

    ev_text = (
        "Illustrative exclusions: non-medically necessary treatment or hospitalization; "
        "cosmetic surgery; expenses within an unexpired waiting period; "
        "and amounts exceeding applicable benefit limits or remaining sum insured."
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[
            ReviewReportEvidenceChunk(
                chunk_id="chunk-pol-1",
                document_id="doc-pol-1",
                filename="policy_v3.pdf",
                page_number=2,
                chunk_index=0,
                text=ev_text,
            )
        ],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "Intake completed"}),
        evidence_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(
            status="insufficient_evidence",
            analysis={
                "summary": "Policy exclusion reviewed",
                "relevant_clauses": [
                    {
                        "finding": "Exclusion for expenses within unexpired waiting period.",
                        "explanation": "Policy exclusion clause.",
                        "supporting_evidence_ids": ["chunk-pol-1"],
                        "supporting_quotes": [
                            {
                                "evidence_id": "chunk-pol-1",
                                "quote": "Illustrative exclusions: non-medically necessary treatment or hospitalization; ... expenses within an unexpired waiting period; and amounts exceeding applicable benefit limits",
                            }
                        ],
                    }
                ],
            },
        ),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="unavailable", analysis=None),
    )

    # 1. Validation must succeed without raising ReviewReportAgentError
    ev_map = _validate_input(report_input)
    assert "chunk-pol-1" in ev_map

    # 2. Fallback partial report must synthesize policy clause cleanly
    fallback = build_fallback_partial_report(report_input=report_input)
    assert isinstance(fallback, ReviewReportOutput)
    assert fallback.overall_status == "incomplete"
    assert fallback.human_review_required is True
    assert len(fallback.observed_facts) >= 1
    assert "Exclusion" in fallback.observed_facts[0].statement


def test_risk_anomaly_accepts_empty_citations_for_missing_info_and_hypotheses(monkeypatch: pytest.MonkeyPatch):
    """Missing information and hypotheses represent gaps, so empty citations must not raise an error."""
    chunk_id = "chunk-test-1"
    doc_id = "doc-test-1"
    claim_evidence = [
        {
            "chunk_id": chunk_id,
            "document_id": doc_id,
            "filename": "discharge_summary.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Patient was admitted for emergency appendectomy on 10 Feb 2026.",
        }
    ]
    extraction = RiskAnomalyExtraction(
        observed_facts=[
            RiskAnomalyFindingExtraction(
                finding="Patient admitted on 10 Feb 2026 for surgery.",
                explanation="Verified from hospital discharge summary.",
                supporting_evidence_ids=[chunk_id],
                supporting_quotes=[
                    RiskAnomalyEvidenceQuote(
                        evidence_id=chunk_id,
                        quote="Patient was admitted for emergency appendectomy on 10 Feb 2026.",
                    )
                ],
            )
        ],
        anomalies=[],
        hypotheses=[
            RiskAnomalyFindingExtraction(
                finding="Pre-authorization was not initiated prior to admission.",
                explanation="Emergency status may explain lack of prior authorization.",
                supporting_evidence_ids=[],
                supporting_quotes=[],
            )
        ],
        missing_information=[
            RiskAnomalyFindingExtraction(
                finding="Histopathology / biopsy report is missing.",
                explanation="No pathology report was provided to confirm acute appendicitis diagnosis.",
                supporting_evidence_ids=[],
                supporting_quotes=[],
            )
        ],
    )

    fake_model = MagicMock()
    fake_model.with_structured_output.return_value = fake_model
    fake_model.invoke.return_value = extraction
    monkeypatch.setattr("claimsage.agents.risk_anomaly_agent.get_chat_model", lambda: fake_model)

    output = analyze_risk_and_anomalies(
        task="Analyze risk and missing evidence.",
        claim_facts={"claim_type": "health"},
        claim_evidence=claim_evidence,
    )

    assert isinstance(output, RiskAnomalyOutput)
    assert output.overall_status == "analyzed"
    assert len(output.observed_facts) == 1
    assert output.observed_facts[0].supporting_evidence_ids == [chunk_id]
    assert len(output.hypotheses) == 1
    assert output.hypotheses[0].supporting_evidence_ids == []
    assert len(output.missing_information) == 1
    assert output.missing_information[0].supporting_evidence_ids == []


def test_fallback_partial_report_eliminates_policy_absence_contradiction_and_synthesizes_room_rent():
    """Verify contradiction removal and room rent comparison fact synthesis."""
    bill_chunk_id = "chunk-bill-4500"
    policy_chunk_id = "chunk-pol-5000"

    bill_text = "BREAKDOWN OF CHARGES: 1. Room & Nursing Charges (General Ward): 3 days @ INR 4,500.00 = INR 13,500.00 (Room rent is within policy sub-limit of INR 5,000 per day)"
    policy_text = "3. Limits and Cost-Sharing Benefit Room rent INR 5,000 per day ICU room charges INR 10,000 per day"

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "claim_id": "CLM-DEMO-HEALTH-001"},
        retrieved_evidence=[
            ReviewReportEvidenceChunk(
                chunk_id=bill_chunk_id,
                document_id="doc-bill",
                filename="health_claim1_itemized_bill.pdf",
                page_number=1,
                chunk_index=0,
                text=bill_text,
            ),
            ReviewReportEvidenceChunk(
                chunk_id=policy_chunk_id,
                document_id="doc-pol",
                filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
                page_number=1,
                chunk_index=1,
                text=policy_text,
            ),
        ],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "Intake completed"}),
        evidence_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "summary": "Evidence analysis complete",
                "factual_findings": [
                    {
                        "finding": "Room rent is claimed at INR 4,500 per day",
                        "explanation": "The physician note explicitly mentions the policy sub-limit, but the policy document itself is not provided for verification.",
                        "supporting_evidence_ids": [bill_chunk_id],
                        "supporting_quotes": [
                            {
                                "evidence_id": bill_chunk_id,
                                "quote": "Room & Nursing Charges (General Ward): 3 days @ INR 4,500.00 = INR 13,500.00",
                            }
                        ],
                    }
                ],
            },
        ),
        policy_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="unavailable", analysis=None),
    )

    fallback = build_fallback_partial_report(report_input=report_input)

    # 1. Contradiction "the policy document itself is not provided" must be sanitized
    for fact in fallback.observed_facts:
        assert "not provided for verification" not in fact.explanation

    # 2. Ground-truth room rent comparison fact must be synthesized
    room_rent_fact = next(
        (f for f in fallback.observed_facts if "4,500" in f.statement and "5,000" in f.statement),
        None,
    )
    assert room_rent_fact is not None, "Room rent comparison fact was not synthesized"
    assert set(room_rent_fact.supporting_evidence_ids) == {bill_chunk_id, policy_chunk_id}
    assert len(room_rent_fact.supporting_quotes) == 2
    assert fallback.overall_status == "incomplete"


def test_quote_matches_evidence_normalizes_unicode_hyphens_and_spaces():
    """Verify that typography emitted by modern LLMs matches ASCII source texts."""
    from claimsage.agents.llm import quote_matches_evidence

    # Non-breaking hyphen (\u2011) in quote vs ASCII hyphen (-) in source
    source = "Initial illness waiting period 30 days from policy commencement; accident-related emergency treatment excepted"
    quote = "Initial illness waiting period 30 days from policy commencement; accident\u2011related emergency treatment excepted"
    assert quote_matches_evidence(quote, source) is True

    # Narrow no-break space (\u202f) in currency/amounts vs standard space
    source2 = "3. Limits and Cost-Sharing Benefit Room rent INR 5,000 per day ICU room charges INR 10,000 per day"
    quote2 = "Room rent INR\u202f5,000 per day"
    assert quote_matches_evidence(quote2, source2) is True


def test_review_report_validates_analyst_references_with_empty_evidence_ids():
    """Ensure _validate_analyst_references accepts findings with empty supporting_evidence_ids (e.g. from missing info)."""
    from claimsage.agents.review_report_agent import _validate_analyst_references
    from claimsage.agents.schemas import ReviewReportEvidenceChunk

    evidence_by_id = {
        "ev-1": ReviewReportEvidenceChunk(
            chunk_id="ev-1",
            document_id="doc-1",
            filename="bill.pdf",
            page_number=1,
            chunk_index=0,
            text="Bill total INR 4,500.",
        )
    }

    # Finding with empty supporting_evidence_ids must not raise ReviewReportAgentError
    gap_finding = {
        "finding": "Missing ultrasound report",
        "explanation": "No diagnostic report was provided.",
        "supporting_evidence_ids": [],
    }
    _validate_analyst_references(gap_finding, evidence_by_id)
