"""Comprehensive regression tests for Global Investigation Report Quality and Consistency Guarantees.

Covers all 17 required verification scenarios across multiple synthetic claimants
and insurance types (health, motor/auto, property) without live LLM calls.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from claimsage.agents import graph as graph_module
from claimsage.agents import review_report_agent as report_module
from claimsage.agents.report_validation import (
    build_source_inventory,
    check_statement_supports_reference,
    detect_cross_source_discrepancies,
    extract_structured_values,
    finalize_and_validate_report,
    index_specialist_findings,
    parse_date_string,
    reconcile_missing_information,
    resolve_true_originating_specialist,
    validate_and_attribute_items,
    validate_partial_dates_in_report,
)
from claimsage.agents.review_report_agent import (
    ReviewReportAgentError,
    _canonicalize_live_extraction,
    analyze_review_report,
    build_fallback_partial_report,
)
from claimsage.agents.schemas import (
    ReviewReportAnalystOutputReference,
    ReviewReportEvidenceChunk,
    ReviewReportEvidenceQuote,
    ReviewReportExtraction,
    ReviewReportInput,
    ReviewReportItem,
    ReviewReportItemExtraction,
    ReviewReportSourceReference,
    ReviewReportSpecialistCoverage,
    ReviewReportSpecialistInput,
)


def _chunk(
    *,
    filename: str,
    text: str,
    page_number: int = 1,
    document_id: str | None = None,
    chunk_id: str | None = None,
    clause_identifier: str | None = None,
    verification_status: str | None = None,
    policy_identifier: str | None = None,
) -> ReviewReportEvidenceChunk:
    return ReviewReportEvidenceChunk(
        chunk_id=chunk_id or str(uuid4()),
        document_id=document_id or str(uuid4()),
        filename=filename,
        page_number=page_number,
        chunk_index=0,
        text=text,
        extraction_method="native",
        clause_identifier=clause_identifier,
        verification_status=verification_status,
        policy_identifier=policy_identifier,
    )


def _spec(
    status: str = "skipped",
    analysis: dict[str, object] | None = None,
    limitations: list[str] | None = None,
) -> ReviewReportSpecialistInput:
    return ReviewReportSpecialistInput(
        status=status,
        analysis=analysis,
        limitations=limitations or [],
    )


def _mock_llm(monkeypatch: pytest.MonkeyPatch, extraction: ReviewReportExtraction) -> MagicMock:
    structured = MagicMock()
    structured.invoke.return_value = extraction
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(report_module, "get_chat_model", lambda: model)
    return structured


# ---------------------------------------------------------------------------
# 1. Correct Source Attribution Across Multiple Specialists
# ---------------------------------------------------------------------------


def test_01_correct_source_attribution_across_multiple_specialists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify findings receive accurate originating_specialist attribution and
    echoed findings in risk_anomaly_agent resolve to the true upstream specialist.
    """
    ev_intake = _chunk(
        filename="claimant_form_ananya.pdf",
        text="Claimant Name: Ananya Sharma | Registration Number: MH-14-DN-7788",
    )
    ev_damage = _chunk(
        filename="survey_inspection_ananya.pdf",
        text="Rear bumper impact dent observed during workshop inspection.",
    )
    ev_estimate = _chunk(
        filename="garage_estimate_ananya.pdf",
        text="Total Repair Estimate: INR 38,500 including rear bumper assembly replacement.",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[ev_intake, ev_damage, ev_estimate],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "extracted_fields": [
                    {
                        "field_name": "registration_number",
                        "value": "Registration Number: MH-14-DN-7788",
                        "source_evidence_ids": [ev_intake.chunk_id],
                    }
                ]
            },
        ),
        evidence_analyst=_spec(
            "completed",
            {
                "factual_findings": [
                    {
                        "finding": "Rear bumper impact dent observed during workshop inspection.",
                        "supporting_evidence_ids": [ev_damage.chunk_id],
                    }
                ]
            },
        ),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec(
            "completed",
            {
                "findings": [
                    {
                        "description": "Total Repair Estimate: INR 38,500 including rear bumper assembly replacement.",
                        "source_evidence_ids": [ev_estimate.chunk_id],
                    }
                ]
            },
        ),
        risk_anomaly_agent=_spec(
            "completed",
            {
                "observed_facts": [
                    {
                        # Echoes the exact finding from repair_estimate_analyst
                        "finding": "Total Repair Estimate: INR 38,500 including rear bumper assembly replacement.",
                        "supporting_evidence_ids": [ev_estimate.chunk_id],
                    }
                ],
                "hypotheses": [
                    {
                        "finding": "Rear impact severity should be compared against bracket labor hours.",
                    }
                ],
            },
        ),
    )

    extraction = ReviewReportExtraction(
        observed_facts=[
            ReviewReportItemExtraction(
                statement=ev_damage.text,
                explanation="Observed directly in the workshop inspection report.",
                supporting_evidence_ids=[ev_damage.chunk_id],
                supporting_quotes=[
                    ReviewReportEvidenceQuote(
                        evidence_id=ev_damage.chunk_id,
                        quote=ev_damage.text,
                    )
                ],
            )
        ],
        analyst_interpretations=[
            ReviewReportItemExtraction(
                statement="Total Repair Estimate: INR 38,500 including rear bumper assembly replacement.",
                explanation="Repair estimate line item for rear bumper replacement.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="risk_anomaly_agent",
                        output_path="/observed_facts/0/finding",
                        finding_text="Total Repair Estimate: INR 38,500 including rear bumper assembly replacement.",
                    )
                ],
                limitation="Subject to human adjuster verification of parts invoice.",
            )
        ],
        hypotheses=[
            ReviewReportItemExtraction(
                statement="Rear impact severity should be compared against bracket labor hours.",
                explanation="Risk specialist noted a follow-up check on bracket labor.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="risk_anomaly_agent",
                        output_path="/hypotheses/0/finding",
                        finding_text="Rear impact severity should be compared against bracket labor hours.",
                    )
                ],
                limitation="Hypothesis requires physical surveyor verification.",
            )
        ],
    )
    _mock_llm(monkeypatch, extraction)

    report = analyze_review_report(report_input=report_input)

    # 1. Observed fact from damage chunk resolves to evidence_analyst (which extracted it)
    assert report.observed_facts[0].originating_specialist == "evidence_analyst"
    assert report.observed_facts[0].attribution_status == "verified"

    # 2. Interpretation that cited risk_anomaly_agent's echoed finding is attributed
    # to the true upstream specialist (repair_estimate_analyst), NOT risk_anomaly_agent!
    assert (
        report.analyst_interpretations[0].originating_specialist
        == "repair_estimate_analyst"
    )
    assert report.analyst_interpretations[0].attribution_status == "verified"

    # 3. Genuine risk hypothesis originates from risk_anomaly_agent
    assert report.hypotheses[0].originating_specialist == "risk_anomaly_agent"


# ---------------------------------------------------------------------------
# 2. Incorrect or Unrelated Finding References
# ---------------------------------------------------------------------------


def test_02_incorrect_or_unrelated_finding_references() -> None:
    """Verify unrelated finding references are rejected in live canonicalization
    and flagged as unverified when reused for unrelated statements.
    """
    ev = _chunk(
        filename="clinical_notes.pdf",
        text="Patient admitted on 12 May 2026 with acute bronchitis.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "extracted_fields": [
                    {
                        "field_name": "admission_date",
                        "value": "Patient admitted on 12 May 2026 with acute bronchitis.",
                        "source_evidence_ids": [ev.chunk_id],
                    }
                ]
            },
        ),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )

    # Unrelated model item in live extraction must NOT steal intake_agent's admission_date reference
    raw_extraction = ReviewReportExtraction(
        analyst_interpretations=[
            ReviewReportItemExtraction(
                statement="Ambulance tariff exceeded metropolitan schedule.",
                explanation="Unrelated statement about ambulance charges.",
                analyst_output_references=[],
                limitation="Requires verification.",
            )
        ]
    )
    canonical = _canonicalize_live_extraction(
        raw_extraction,
        report_input=report_input,
        evidence_by_id={ev.chunk_id: ev},
    )
    assert all(
        "ambulance" not in item.explanation.casefold()
        for item in canonical.analyst_interpretations
    )

    # Also test validate_and_attribute_items when a reference is reused for an unrelated second item
    indexed = index_specialist_findings(report_input)
    ref = ReviewReportAnalystOutputReference(
        specialist="intake_agent",
        output_path="/extracted_fields/0/value",
        finding_text="Patient admitted on 12 May 2026 with acute bronchitis.",
    )
    items = [
        ReviewReportItem(
            statement="Patient admitted on 12 May 2026 with acute bronchitis.",
            explanation="Admission date extracted by intake agent.",
            analyst_output_references=[ref],
            source_basis="analyst_output",
            limitation="Requires verification.",
        ),
        ReviewReportItem(
            statement="Pharmacy implant serial number was not listed.",
            explanation="Unrelated pharmacy statement reusing the same reference.",
            analyst_output_references=[ref],
            source_basis="analyst_output",
            limitation="Requires verification.",
        ),
    ]
    warnings: list[str] = []
    attributed = validate_and_attribute_items(
        items,
        category="analyst_interpretations",
        indexed_findings=indexed,
        evidence_by_id={ev.chunk_id: ev},
        used_references={},
        warnings=warnings,
    )
    assert attributed[0].attribution_status == "verified"
    assert attributed[1].attribution_status == "unverified"
    assert any("reused" in w or "does not support" in w for w in warnings)


# ---------------------------------------------------------------------------
# 3. Missing Information That Exists in Another Retrieved Source
# ---------------------------------------------------------------------------


def test_03_missing_information_reconciled_when_present_in_another_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify false-positive missing-information items are removed when another
    retrieved document contains the information.
    """
    rc_chunk = _chunk(
        filename="rohan_vehicle_rc_and_dl.pdf",
        text="Vehicle Registration Number: KA-05-MN-4321 | Driving Licence No: KA0520190012345 valid until 2032.",
    )
    est_chunk = _chunk(
        filename="rohan_repair_estimate.pdf",
        text="Total Repair Estimate: INR 54,200 (Front headlamp and bumper repair).",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto"},
        retrieved_evidence=[rc_chunk, est_chunk],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "missing_information": [
                    "Driving licence and registration certificate (RC) were not provided.",
                    "Repair estimate document is missing.",
                ]
            },
        ),
        evidence_analyst=_spec("completed", {"factual_findings": []}),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )

    extraction = ReviewReportExtraction(
        observed_facts=[
            ReviewReportItemExtraction(
                statement=rc_chunk.text,
                explanation="Registration and driving licence details from RC/DL document.",
                supporting_evidence_ids=[rc_chunk.chunk_id],
                supporting_quotes=[
                    ReviewReportEvidenceQuote(
                        evidence_id=rc_chunk.chunk_id,
                        quote=rc_chunk.text,
                    )
                ],
            )
        ],
        missing_information=[
            ReviewReportItemExtraction(
                statement="Driving licence and registration certificate (RC) were not provided.",
                explanation="Intake specialist noted RC/DL as missing.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="intake_agent",
                        output_path="/missing_information/0",
                        finding_text="Driving licence and registration certificate (RC) were not provided.",
                    )
                ],
                limitation="Absence requires review.",
            ),
            ReviewReportItemExtraction(
                statement="Repair estimate document is missing.",
                explanation="Intake specialist noted repair estimate as missing.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="intake_agent",
                        output_path="/missing_information/1",
                        finding_text="Repair estimate document is missing.",
                    )
                ],
                limitation="Absence requires review.",
            ),
        ],
    )
    _mock_llm(monkeypatch, extraction)

    report = analyze_review_report(report_input=report_input)

    # Both items exist in retrieved evidence (rohan_vehicle_rc_and_dl.pdf and rohan_repair_estimate.pdf)
    # so neither may remain in report.missing_information!
    assert report.missing_information == []
    assert len(report.missing_information_reconciliation) == 2
    for rec in report.missing_information_reconciliation:
        assert rec.retained_in_missing_information is False
        assert rec.available_in_sources
        assert rec.supporting_evidence_ids


# ---------------------------------------------------------------------------
# 4. Information That Is Genuinely Unavailable (not_provided vs not_retrieved)
# ---------------------------------------------------------------------------


def test_04_genuinely_unavailable_missing_information_classified_as_not_provided_or_not_retrieved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify genuinely missing items are classified as not_provided or not_retrieved."""
    ev = _chunk(
        filename="admission_note.pdf",
        text="Patient admitted for observation on 03 June 2026.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[ev],
        uploaded_documents=[
            {
                "document_id": "doc-unretrieved- toxicology",
                "filename": "toxicology_screening_lab.pdf",
                "processing_status": "failed",
            }
        ],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "missing_information": [
                    "Attending physician fitness certificate was not provided.",
                    "Toxicology screening lab report was not retrieved.",
                ]
            },
        ),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )

    extraction = ReviewReportExtraction(
        missing_information=[
            ReviewReportItemExtraction(
                statement="Attending physician fitness certificate was not provided.",
                explanation="No fitness certificate was supplied in the claim package.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="intake_agent",
                        output_path="/missing_information/0",
                        finding_text="Attending physician fitness certificate was not provided.",
                    )
                ],
                limitation="This absence does not establish lack of medical necessity.",
            ),
            ReviewReportItemExtraction(
                statement="Toxicology screening lab report was not retrieved.",
                explanation="The uploaded toxicology lab file was not retrieved.",
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="intake_agent",
                        output_path="/missing_information/1",
                        finding_text="Toxicology screening lab report was not retrieved.",
                    )
                ],
                limitation="This absence requires manual document inspection.",
            ),
        ]
    )
    _mock_llm(monkeypatch, extraction)

    report = analyze_review_report(report_input=report_input)

    assert len(report.missing_information) == 2
    by_stmt = {i.statement: i for i in report.missing_information}
    assert (
        by_stmt["Attending physician fitness certificate was not provided."].missing_category
        == "not_provided"
    )
    assert (
        by_stmt["Toxicology screening lab report was not retrieved."].missing_category
        == "not_retrieved"
    )


# ---------------------------------------------------------------------------
# 5. Partial Dates and Incomplete Values
# ---------------------------------------------------------------------------


def test_05_partial_dates_and_incomplete_values_preserved_without_inference() -> None:
    """Verify partial dates ('20 March', 'March 2026', '20/03') are preserved as
    partial and any fabricated year in a report item is stripped and flagged.
    """
    assert parse_date_string("20 March") == ("20 March", "PARTIAL:--03-20", True)
    assert parse_date_string("March 2026") == ("March 2026", "PARTIAL:2026-03--", True)
    assert parse_date_string("20/03") == ("20/03", "PARTIAL:--03-20", True)
    assert parse_date_string("20 March 2026") == ("20 March 2026", "2026-03-20", False)

    partial_ev = _chunk(
        filename="handwritten_statement.pdf",
        text="Incident Date: 20 March | Inspection Date: 25 March 2026.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto"},
        retrieved_evidence=[partial_ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    ev_map = {partial_ev.chunk_id: partial_ev}
    extracted = extract_structured_values(report_input, ev_map)

    # Incident date is partial; inspection date is complete; they must NOT conflict!
    disc_facts, disc_conflicts = detect_cross_source_discrepancies(extracted, ev_map)
    assert disc_conflicts == []

    # If a statement fabricates year 2026 onto "20 March", validate_partial_dates_in_report strips the fabricated year
    item_with_inferred_year = ReviewReportItem(
        statement="Incident occurred on 20 March 2026.",
        explanation="Extracted from handwritten statement.",
        supporting_evidence_ids=[partial_ev.chunk_id],
        supporting_quotes=[
            ReviewReportEvidenceQuote(
                evidence_id=partial_ev.chunk_id,
                quote="Incident Date: 20 March",
            )
        ],
        sources=[
            ReviewReportSourceReference(
                evidence_id=partial_ev.chunk_id,
                document_id=str(partial_ev.document_id),
                filename=partial_ev.filename,
                page_number=1,
            )
        ],
        source_basis="retrieved_evidence",
    )
    warnings: list[str] = []
    cleaned = validate_partial_dates_in_report(
        [item_with_inferred_year], extracted, ev_map, warnings
    )
    assert "20 March 2026" not in cleaned[0].statement
    assert "20 March" in cleaned[0].statement
    assert warnings
    assert "partial date" in (cleaned[0].limitation or "").casefold()


# ---------------------------------------------------------------------------
# 6. Conflicting Dates, Identifiers, and Financial Amounts
# ---------------------------------------------------------------------------


def test_06_conflicting_dates_identifiers_and_financial_amounts_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify cross-source conflicts on the same semantic role (date, amount, entity)
    are preserved while distinct financial/date roles are never conflated.
    """
    ev1 = _chunk(
        filename="claim_form_kabir.pdf",
        text=(
            "Incident Date: 10 April 2026 | Registration Number: DL-08-CA-1122 | "
            "Sum Insured: INR 300,000 | Total Claim Amount: INR 65,000"
        ),
    )
    ev2 = _chunk(
        filename="policy_and_survey_kabir.pdf",
        text=(
            "Incident Date: 14 April 2026 | Inspection Date: 16 April 2026 | "
            "Registration Number: DL-08-CA-9988 | Sum Insured: INR 500,000 | "
            "Compulsory Deductible: INR 2,000"
        ),
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto"},
        retrieved_evidence=[ev1, ev2],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    # Must detect conflicts for:
    # 1. Incident Date (10 April 2026 vs 14 April 2026) — NOT Inspection Date (16 April 2026)
    # 2. Sum Insured (INR 300,000 vs INR 500,000) — NOT Deductible (INR 2,000) or Claimed Amount (INR 65,000)
    # 3. Vehicle Registration Number (DL-08-CA-1122 vs DL-08-CA-9988)
    conflict_Execution = [c.statement for c in report.conflicting_findings]
    assert len(report.conflicting_findings) == 3
    assert any("10 April 2026" in s and "14 April 2026" in s for s in conflict_Execution)
    assert any("INR 300,000" in s and "INR 500,000" in s for s in conflict_Execution)
    assert any("DL-08-CA-1122" in s and "DL-08-CA-9988" in s for s in conflict_Execution)
    # Ensure Inspection Date (16 April 2026) and Deductible (INR 2,000) were NOT falsely treated as conflicting
    assert all("16 April 2026" not in s for s in conflict_Execution)
    assert all("INR 2,000" not in s for s in conflict_Execution)


# ---------------------------------------------------------------------------
# 7. Retrieved But Unverified Policy Evidence
# ---------------------------------------------------------------------------


def test_07_retrieved_unverified_policy_evidence_classification_and_transparency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pending_review policy clauses are classified as retrieved_unverified,
    never reported as absent, and set policy_verification_status='pending_review'.
    """
    pol_chunk = _chunk(
        filename="health_policy_wording_v2.pdf",
        text="Section 4: Cataract surgical limit is INR 40,000 per eye.",
        clause_identifier="4.1",
        verification_status="pending_review",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[pol_chunk],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "missing_information": [
                    "Policy document and coverage terms were not provided."
                ]
            },
        ),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec(
            "completed",
            {
                "relevant_clauses": [
                    {
                        "finding": "Section 4: Cataract surgical limit is INR 40,000 per eye.",
                        "explanation": "Retrieved from policy wording.",
                        "supporting_evidence_ids": [pol_chunk.chunk_id],
                    }
                ]
            },
        ),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    assert report.policy_verification_status == "pending_review"
    assert report.report_validation_status == "flagged_for_human_review"
    # False claim that policy document was not provided is removed from missing_information
    assert report.missing_information == []
    assert any(
        r.reconciled_category == "retrieved_unverified"
        for r in report.missing_information_reconciliation
    )
    assert any("pending_review" in w for w in report.validation_warnings)


# ---------------------------------------------------------------------------
# 8. Specialist-Specific Document Retrieval Appearing in Final Inventory
# ---------------------------------------------------------------------------


def test_08_specialist_specific_document_retrieval_appears_in_source_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify documents resolved by specialist-specific tools (repair_estimate_analyst)
    appear in source_inventory with retrieval_status='specialist_retrieved' and accurate usage.
    """
    claim_chunk = _chunk(
        filename="accident_report.pdf",
        text="Front left fender damaged in parking lot collision.",
    )
    estimate_chunk = _chunk(
        filename="authorized_workshop_estimate.pdf",
        text="Line item 1: Front left fender replacement INR 14,500.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto"},
        retrieved_evidence=[claim_chunk, estimate_chunk],
        specialist_evidence_usage={
            "repair_estimate_channel": [estimate_chunk.chunk_id],
            "repair_estimate_analyst": [estimate_chunk.chunk_id],
        },
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec(
            "completed",
            {
                "line_items": [
                    {
                        "description": "Front left fender replacement INR 14,500.",
                        "source_evidence_ids": [estimate_chunk.chunk_id],
                    }
                ]
            },
        ),
        risk_anomaly_agent=_spec("skipped"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    inv_by_file = {item.filename: item for item in report.source_inventory}
    assert "authorized_workshop_estimate.pdf" in inv_by_file
    est_inv = inv_by_file["authorized_workshop_estimate.pdf"]
    assert est_inv.document_type == "repair_estimate"
    assert est_inv.retrieval_status == "specialist_retrieved"
    assert "repair_estimate_analyst" in est_inv.used_by_specialists
    assert "policy_analyst" not in est_inv.used_by_specialists


# ---------------------------------------------------------------------------
# 9. Duplicate Source-Document Prevention & Uploaded vs Retrieved Distinction
# ---------------------------------------------------------------------------


def test_09_duplicate_source_document_prevention_and_uploaded_vs_retrieved_distinction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify multiple chunks from the same document produce a single source_inventory
    entry and uploaded-but-unretrieved documents are marked uploaded_not_retrieved with empty usage.
    """
    shared_doc_id = str(uuid4())
    chunk_p1 = _chunk(
        document_id=shared_doc_id,
        filename="discharge_summary_priya.pdf",
        page_number=1,
        text="Patient Name: Priya Nair | Admitted on 01 May 2026.",
    )
    chunk_p2 = _chunk(
        document_id=shared_doc_id,
        filename="discharge_summary_priya.pdf",
        page_number=2,
        text="Discharged on 05 May 2026 in stable condition.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[chunk_p1, chunk_p2],
        uploaded_documents=[
            {
                "document_id": shared_doc_id,
                "filename": "discharge_summary_priya.pdf",
                "processing_status": "processed",
            },
            {
                "document_id": "doc-unretrieved-ecg",
                "filename": "ecg_tracing_unretrieved.pdf",
                "processing_status": "uploaded",
            },
        ],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec(
            "completed",
            {
                "factual_findings": [
                    {
                        "finding": "Discharged on 05 May 2026 in stable condition.",
                        "supporting_evidence_ids": [chunk_p2.chunk_id],
                    }
                ]
            },
        ),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    assert len(report.source_inventory) == 2
    by_name = {item.filename: item for item in report.source_inventory}

    discharge_inv = by_name["discharge_summary_priya.pdf"]
    assert discharge_inv.document_id == shared_doc_id
    assert discharge_inv.retrieval_status == "retrieved"
    assert discharge_inv.page_numbers == [1, 2]
    assert len(discharge_inv.evidence_ids) == 2
    assert discharge_inv.used_by_specialists == ["evidence_analyst"]

    ecg_inv = by_name["ecg_tracing_unretrieved.pdf"]
    assert ecg_inv.retrieval_status == "uploaded_not_retrieved"
    assert ecg_inv.used_by_specialists == []
    assert ecg_inv.citation_count == 0


# ---------------------------------------------------------------------------
# 10. Failed and Skipped Specialists
# ---------------------------------------------------------------------------


def test_10_failed_and_skipped_specialists_disclosed_and_never_claimed_as_document_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed/unavailable and skipped specialists are disclosed in coverage
    and validation warnings, and never listed in source_inventory.used_by_specialists.
    """
    ev = _chunk(
        filename="hospital_bill.pdf",
        text="Final Hospital Bill: INR 82,000.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec(
            "unavailable",
            limitations=["Evidence Analyst timed out."],
        ),
        policy_analyst=_spec(
            "failed",
            limitations=["Policy Analyst encountered provider error."],
        ),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("unavailable"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    assert report.overall_status == "incomplete"
    assert report.report_completeness == "partial"
    assert report.report_validation_status == "flagged_for_human_review"
    assert len(report.validation_warnings) >= 3
    for inv in report.source_inventory:
        assert "evidence_analyst" not in inv.used_by_specialists
        assert "policy_analyst" not in inv.used_by_specialists
        assert "repair_estimate_analyst" not in inv.used_by_specialists
        assert "risk_anomaly_agent" not in inv.used_by_specialists


# ---------------------------------------------------------------------------
# 11. Invalid Citations and Unsupported Statements
# ---------------------------------------------------------------------------


def test_11_invalid_citations_and_unsupported_statements_rejected_or_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fabricated citations, non-matching quotes, and autonomous decision language fail safely."""
    ev = _chunk(
        filename="claim_note.pdf",
        text="Admission Date: 18 July 2026.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("completed", {"extracted_fields": []}),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )

    # Case A: Fabricated evidence ID
    _mock_llm(
        monkeypatch,
        ReviewReportExtraction(
            observed_facts=[
                ReviewReportItemExtraction(
                    statement="Admission Date: 18 July 2026.",
                    explanation="Cited with fake ID.",
                    supporting_evidence_ids=["non-existent-chunk-id"],
                    supporting_quotes=[
                        ReviewReportEvidenceQuote(
                            evidence_id="non-existent-chunk-id",
                            quote="Admission Date: 18 July 2026.",
                        )
                    ],
                )
            ]
        ),
    )
    with pytest.raises(ReviewReportAgentError, match="not retrieved"):
        analyze_review_report(report_input=report_input)

    # Case B: Prohibited autonomous claim decision language
    _mock_llm(
        monkeypatch,
        ReviewReportExtraction(
            observed_facts=[
                ReviewReportItemExtraction(
                    statement="The claim is approved for immediate settlement.",
                    explanation="Autonomous decision text.",
                    supporting_evidence_ids=[ev.chunk_id],
                    supporting_quotes=[
                        ReviewReportEvidenceQuote(
                            evidence_id=ev.chunk_id,
                            quote=ev.text,
                        )
                    ],
                )
            ]
        ),
    )
    with pytest.raises(ReviewReportAgentError):
        analyze_review_report(report_input=report_input)


# ---------------------------------------------------------------------------
# 12. Health Insurance Investigations End-to-End Quality Guarantees
# ---------------------------------------------------------------------------


def test_12_health_insurance_investigation_end_to_end_quality_guarantees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end verification for a synthetic health insurance investigation."""
    discharge_ev = _chunk(
        filename="meera_discharge_summary.pdf",
        text="Patient Name: Meera Krishnan | Admission Date: 02 August 2026 | Discharge Date: 05 August 2026.",
    )
    bill_ev = _chunk(
        filename="meera_itemized_hospital_bill.pdf",
        text="Total Medical Expenses: INR 92,400 | Room & Nursing Charges: 3 days @ INR 3,800 per day.",
    )
    pol_ev = _chunk(
        filename="health_shield_policy_2026.pdf",
        text="Policy Number: POL-HLTH-9001 | Sum Insured: INR 500,000 | Benefit Room rent INR 4,500 per day.",
        clause_identifier="3.2",
        verification_status="verified",
        policy_identifier="POL-HLTH-9001",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "status": "under_review"},
        retrieved_evidence=[discharge_ev, bill_ev, pol_ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "extracted_fields": [
                    {
                        "field_name": "patient_name",
                        "value": "Patient Name: Meera Krishnan",
                        "source_evidence_ids": [discharge_ev.chunk_id],
                    }
                ],
                "missing_information": [
                    # Inapplicable motor item + already-present discharge summary
                    "Vehicle registration certificate (RC) and repair estimate not provided.",
                    "Hospital discharge summary is missing.",
                ],
            },
        ),
        evidence_analyst=_spec(
            "completed",
            {
                "factual_findings": [
                    {
                        "finding": "Total Medical Expenses: INR 92,400 | Room & Nursing Charges: 3 days @ INR 3,800 per day.",
                        "supporting_evidence_ids": [bill_ev.chunk_id],
                    }
                ]
            },
        ),
        policy_analyst=_spec(
            "completed",
            {
                "relevant_clauses": [
                    {
                        "finding": "Policy Number: POL-HLTH-9001 | Sum Insured: INR 500,000 | Benefit Room rent INR 4,500 per day.",
                        "supporting_evidence_ids": [pol_ev.chunk_id],
                    }
                ]
            },
        ),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("completed", {"observed_facts": []}),
    )

    extraction = ReviewReportExtraction(
        observed_facts=[
            ReviewReportItemExtraction(
                statement=bill_ev.text,
                explanation="Verified from itemized hospital bill.",
                supporting_evidence_ids=[bill_ev.chunk_id],
                supporting_quotes=[
                    ReviewReportEvidenceQuote(
                        evidence_id=bill_ev.chunk_id,
                        quote=bill_ev.text,
                    )
                ],
            )
        ],
    )
    _mock_llm(monkeypatch, extraction)

    report = analyze_review_report(report_input=report_input)

    assert report.overall_status == "completed"
    assert report.report_completeness == "complete"
    assert report.policy_verification_status == "verified"
    assert report.report_validation_status == "validated"
    # Sum Insured (INR 500,000) vs Medical Expenses (INR 92,400) and Admission vs Discharge dates must NOT conflict!
    assert report.conflicting_findings == []
    # Both false-positive/inapplicable missing items must be excluded from missing_information
    assert report.missing_information == []
    rec_cats = {r.reconciled_category for r in report.missing_information_reconciliation}
    assert "not_applicable" in rec_cats
    assert "retrieved_unverified" in rec_cats
    assert len(report.source_inventory) == 3


# ---------------------------------------------------------------------------
# 13. Motor Insurance Investigations End-to-End Quality Guarantees
# ---------------------------------------------------------------------------


def test_13_motor_insurance_investigation_end_to_end_quality_guarantees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end verification for a synthetic motor insurance investigation."""
    rc_ev = _chunk(
        filename="dev_motor_rc_dl.pdf",
        text="Claimant Name: Devendra Joshi | Registration Number: GJ-01-KR-5566 | Insured Declared Value: INR 720,000",
    )
    est_ev = _chunk(
        filename="dev_workshop_repair_estimate.pdf",
        text="Total Repair Estimate: INR 64,500 | Inspection Date: 09 September 2026",
    )
    pol_ev = _chunk(
        filename="motor_shield_policy_v2.pdf",
        text="Policy Number: POL-MTR-8821 | Insured declared value (IDV): INR 850,000 | Compulsory Deductible: INR 1,500",
        clause_identifier="1.1",
        verification_status="pending_review",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[rc_ev, est_ev, pol_ev],
        specialist_evidence_usage={
            "repair_estimate_channel": [est_ev.chunk_id],
            "repair_estimate_analyst": [est_ev.chunk_id],
        },
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "extracted_fields": [
                    {
                        "field_name": "registration_number",
                        "value": "Registration Number: GJ-01-KR-5566",
                        "source_evidence_ids": [rc_ev.chunk_id],
                    }
                ],
                "missing_information": [
                    "Hospital discharge summary and ICD-10 diagnosis code not provided.",
                    "Driving licence and registration certificate (RC) missing.",
                ],
            },
        ),
        evidence_analyst=_spec("completed", {"factual_findings": []}),
        policy_analyst=_spec(
            "completed",
            {
                "relevant_clauses": [
                    {
                        "finding": pol_ev.text,
                        "supporting_evidence_ids": [pol_ev.chunk_id],
                    }
                ]
            },
        ),
        repair_estimate_analyst=_spec(
            "completed",
            {
                "findings": [
                    {
                        "description": est_ev.text,
                        "source_evidence_ids": [est_ev.chunk_id],
                    }
                ]
            },
        ),
        risk_anomaly_agent=_spec("completed", {"observed_facts": []}),
    )

    _mock_llm(monkeypatch, ReviewReportExtraction())

    report = analyze_review_report(report_input=report_input)

    # 1. IDV conflict (INR 720,000 vs INR 850,000) is preserved; Repair Estimate (INR 64,500) and Deductible (INR 1,500) are not confused with IDV!
    assert len(report.conflicting_findings) == 1
    assert "INR 720,000" in report.conflicting_findings[0].statement
    assert "INR 850,000" in report.conflicting_findings[0].statement

    # 2. Health discharge summary is classified not_applicable; RC/DL is reconciled against dev_motor_rc_dl.pdf
    assert report.missing_information == []
    rec_cats = {r.reconciled_category for r in report.missing_information_reconciliation}
    assert "not_applicable" in rec_cats
    assert "retrieved_unverified" in rec_cats

    # 3. Repair estimate document is in source_inventory as specialist_retrieved
    inv_map = {i.filename: i for i in report.source_inventory}
    assert inv_map["dev_workshop_repair_estimate.pdf"].retrieval_status == "specialist_retrieved"
    assert "repair_estimate_analyst" in inv_map["dev_workshop_repair_estimate.pdf"].used_by_specialists
    assert report.policy_verification_status == "pending_review"
    assert report.report_validation_status == "flagged_for_human_review"


# ---------------------------------------------------------------------------
# 14. Multiple Claimants and Concurrent Investigations
# ---------------------------------------------------------------------------


def test_14_multiple_claimants_and_concurrent_investigations_isolation() -> None:
    """Verify concurrent report validations for distinct claimants have zero cross-contamination."""
    scenarios = [
        (
            "health",
            "Priya Nair",
            "priya_bill.pdf",
            "Claimant Name: Priya Nair | Total Medical Expenses: INR 42,000",
        ),
        (
            "auto",
            "Kabir Mehta",
            "kabir_estimate.pdf",
            "Claimant Name: Kabir Mehta | Total Repair Estimate: INR 88,000",
        ),
        (
            "property",
            "Siddharth Rao",
            "siddharth_survey.pdf",
            "Claimant Name: Siddharth Rao | Total Claim Amount: INR 150,000",
        ),
    ]

    def _run_single(claim_type: str, claimant: str, fname: str, text: str) -> ReviewReportOutput:
        ev = _chunk(filename=fname, text=text)
        inp = ReviewReportInput(
            claim_facts={"claim_type": claim_type},
            retrieved_evidence=[ev],
            evidence_retrieval_status="completed",
            evidence_retrieval_limitations=[],
            intake_agent=_spec("unavailable"),
            evidence_analyst=_spec(
                "completed",
                {
                    "factual_findings": [
                        {
                            "finding": text,
                            "supporting_evidence_ids": [ev.chunk_id],
                        }
                    ]
                },
            ),
            policy_analyst=_spec("skipped"),
            repair_estimate_analyst=_spec("skipped"),
            risk_anomaly_agent=_spec("skipped"),
        )
        return build_fallback_partial_report(report_input=inp)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_run_single, *sc) for sc in scenarios]
        results = [f.result() for f in futures]

    for (_, claimant, fname, _), rep in zip(scenarios, results, strict=True):
        assert len(rep.source_inventory) == 1
        assert rep.source_inventory[0].filename == fname
        assert any(claimant in f.statement for f in rep.observed_facts)
        other_claimants = {"Priya Nair", "Kabir Mehta", "Siddharth Rao"} - {claimant}
        dump_str = str(rep.model_dump(mode="json"))
        for other in other_claimants:
            assert other not in dump_str


# ---------------------------------------------------------------------------
# 15. Deterministic Fallback Report Validation
# ---------------------------------------------------------------------------


def test_15_deterministic_fallback_report_validation() -> None:
    """Verify build_fallback_partial_report runs full reconciliation, source inventory,
    and cross-agent validation when LLM synthesis fails.
    """
    ev_bill = _chunk(
        filename="arjun_hospital_bill.pdf",
        text="Room & Nursing Charges: 2 days @ INR 3,200 per day | Final Hospital Bill: INR 48,000",
    )
    ev_pol = _chunk(
        filename="arjun_health_policy.pdf",
        text="Policy Number: POL-ARJUN-01 | Benefit Room rent INR 4,000 per day",
        clause_identifier="2.1",
        verification_status="pending_review",
        policy_identifier="POL-ARJUN-01",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[ev_bill, ev_pol],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec(
            "completed",
            {
                "missing_information": [
                    "Repair estimate is missing.",
                    "Itemized hospital bill is missing.",
                ]
            },
        ),
        evidence_analyst=_spec(
            "completed",
            {
                "factual_findings": [
                    {
                        "finding": "Room & Nursing Charges: 2 days @ INR 3,200 per day",
                        "explanation": "Extracted from hospital bill, but the policy document itself is not provided for verification.",
                        "supporting_evidence_ids": [ev_bill.chunk_id],
                    }
                ]
            },
        ),
        policy_analyst=_spec("unavailable"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("unavailable"),
    )

    fallback = build_fallback_partial_report(
        report_input=report_input,
        error_message="rate_limited: SyntheticQuotaError",
    )

    assert fallback.overall_status == "incomplete"
    assert fallback.report_completeness == "partial"
    assert fallback.policy_verification_status == "pending_review"
    assert fallback.report_validation_status == "flagged_for_human_review"
    assert len(fallback.source_inventory) == 2
    # Generalized room rent comparison works for INR 3,200 vs INR 4,000 under POL-ARJUN-01!
    assert any(
        "INR 3,200" in f.statement and "INR 4,000" in f.statement and "POL-ARJUN-01" in f.statement
        for f in fallback.observed_facts
    )
    # Inapplicable repair estimate and already-present hospital bill were reconciled out of missing_information
    assert all("repair estimate" not in m.statement.casefold() for m in fallback.missing_information)
    assert all("itemized hospital bill" not in m.statement.casefold() for m in fallback.missing_information)


# ---------------------------------------------------------------------------
# 16. Reports With Incomplete Evidence
# ---------------------------------------------------------------------------


def test_16_reports_with_incomplete_evidence_status_and_transparency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify reports with limited retrieval or zero evidence accurately report completeness."""
    # Case 1: No evidence at all
    empty_input = ReviewReportInput(
        claim_facts={"claim_type": "health"},
        retrieved_evidence=[],
        evidence_retrieval_status="not_performed",
        evidence_retrieval_limitations=[],
        intake_agent=_spec("skipped"),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    empty_report = analyze_review_report(report_input=empty_input)
    assert empty_report.overall_status == "insufficient_evidence"
    assert empty_report.report_completeness == "insufficient_evidence"
    assert empty_report.report_validation_status == "flagged_for_human_review"

    # Case 2: Limited evidence retrieval
    ev = _chunk(filename="partial_claim.pdf", text="Incident Date: 05 May 2026.")
    limited_input = ReviewReportInput(
        claim_facts={"claim_type": "auto"},
        retrieved_evidence=[ev],
        evidence_retrieval_status="limited",
        evidence_retrieval_limitations=["Policy evidence retrieval was unavailable."],
        intake_agent=_spec(
            "completed",
            {"missing_information": [" Surveyor final report was not provided."]},
        ),
        evidence_analyst=_spec("skipped"),
        policy_analyst=_spec("skipped"),
        repair_estimate_analyst=_spec("skipped"),
        risk_anomaly_agent=_spec("skipped"),
    )
    _mock_llm(monkeypatch, ReviewReportExtraction())
    limited_report = analyze_review_report(report_input=limited_input)
    assert limited_report.overall_status == "incomplete"
    assert limited_report.report_completeness == "partial"
    assert limited_report.missing_information[0].missing_category == "not_retrieved"


# ---------------------------------------------------------------------------
# 17. Reports Containing Unresolved Human-Review Requirements & Stage Diagnostics
# ---------------------------------------------------------------------------


def test_17_reports_with_unresolved_human_review_requirements_and_stage_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify run_review_report in graph.py preserves human_review_required=True and
    persists report_validation_status, report_completeness, policy_verification_status,
    and validation_warnings in stage_diagnostics.
    """
    claim_ev = _chunk(
        filename="claim_overview.pdf",
        text="Insured Declared Value: INR 550,000",
    )
    pol_ev = _chunk(
        filename="policy_schedule.pdf",
        text="Insured declared value (IDV): INR 700,000",
        clause_identifier="1",
        verification_status="pending_review",
    )

    state = {
        "task": "Investigate motor claim.",
        "claim_facts": {"claim_id": "clm-17", "claim_type": "auto", "status": "under_review"},
        "claim_evidence": [claim_ev.model_dump(mode="json")],
        "claim_evidence_retrieval_status": "completed",
        "policy_evidence": [pol_ev.model_dump(mode="json")],
        "policy_retrieval_status": "completed",
        "repair_estimate_evidence": [],
        "repair_estimate_document_id": None,
        "selected_analysts": ["intake_agent"],
        "intake_analysis": {
            "summary": "Intake completed.",
            "overall_assessment": "documents_incomplete",
            "human_review_required": True,
        },
        "intake_analysis_status": "completed",
        "evidence_analysis": None,
        "evidence_analysis_status": "skipped",
        "policy_analysis": None,
        "ai_analysis_status": "skipped",
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "skipped",
        "risk_analysis": None,
        "risk_analysis_status": "skipped",
        "result": {"limitations": []},
    }
    _mock_llm(monkeypatch, ReviewReportExtraction())

    update = graph_module.run_review_report(state)

    report: ReviewReportOutput = update["review_report"]
    assert report.human_review_required is True
    assert report.report_validation_status == "flagged_for_human_review"
    assert report.policy_verification_status == "pending_review"
    assert len(report.conflicting_findings) == 1

    diag = update["result"]["stage_diagnostics"]["review_report"]
    assert diag["report_validation_status"] == "flagged_for_human_review"
    assert diag["policy_verification_status"] == "pending_review"
    assert diag["report_completeness"] in {"complete", "partial"}
    assert isinstance(diag["validation_warnings"], list)
    assert len(diag["validation_warnings"]) >= 1
