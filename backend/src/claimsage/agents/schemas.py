"""Structured output schemas for ClaimSage specialist agents."""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_additional_properties(schema: dict[str, Any]) -> None:
    """Remove additionalProperties from generated JSON schemas for Gemini API compatibility
    while preserving strict extra='forbid' Pydantic runtime validation.
    """
    schema.pop("additionalProperties", None)
    for value in list(schema.values()):
        if isinstance(value, dict):
            _strip_additional_properties(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_additional_properties(item)


_STRICT_SCHEMA_CONFIG = ConfigDict(
    extra="forbid",
    json_schema_extra=_strip_additional_properties,
)


class PolicyEvidenceQuote(BaseModel):
    """Verbatim source excerpt supporting a policy analyst interpretation."""

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=8)


class PolicyClauseFinding(BaseModel):
    """A policy finding grounded in retrieved evidence."""

    finding: str = Field(
        description="A concise finding about a relevant policy provision."
    )
    supporting_evidence_ids: list[str] = Field(
        min_length=1,
        description="Exact evidence chunk IDs supporting this finding."
    )
    supporting_quotes: list[PolicyEvidenceQuote] = Field(
        min_length=1,
        description="Verbatim excerpts from the cited policy evidence.",
    )
    explanation: str = Field(
        description="Why the cited policy evidence matters to the investigation."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in the interpretation, not certainty of coverage."
    )


class PolicyDerivedConclusion(BaseModel):
    """Policy interpretation with canonical source IDs and exact excerpts."""

    conclusion: str = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    supporting_quotes: list[PolicyEvidenceQuote] = Field(min_length=1)


class PolicyAnalystOutput(BaseModel):
    """Structured policy analysis produced by the Policy Analyst."""

    summary: str = Field(
        description="Concise summary of the policy evidence relevant to the task."
    )
    summary_quotes: list[PolicyEvidenceQuote] = Field(default_factory=list)
    assessment_quotes: list[PolicyEvidenceQuote] = Field(default_factory=list)
    relevant_clauses: list[PolicyClauseFinding] = Field(
        default_factory=list
    )
    coverage_indicators: list[PolicyDerivedConclusion] = Field(
        default_factory=list,
        description=(
            "Policy provisions that may support coverage. Every conclusion "
            "must include canonical evidence IDs and exact source quotations."
        ),
    )
    exclusions_and_conditions: list[PolicyDerivedConclusion] = Field(
        default_factory=list,
        description=(
            "Relevant exclusions, limitations, conditions, and requirements. "
            "Every conclusion must include canonical evidence IDs and exact "
            "source quotations."
        ),
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Information needed to interpret the policy reliably."
    )
    evidence_gaps: list[str] = Field(
        default_factory=list,
        description="Questions that retrieved evidence does not resolve."
    )
    overall_assessment: Literal[
        "potentially_supportive",
        "potentially_restrictive",
        "mixed",
        "insufficient_evidence",
    ] = Field(
        description="Preliminary evidence assessment, not a coverage decision."
    )
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


class ClaimEvidenceFinding(BaseModel):
    """A factual finding grounded in retrieved claim evidence."""

    finding: str
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="Exact evidence chunk IDs supporting this finding.")
    explanation: str
    confidence: Literal["high", "medium", "low"]


class ClaimTimelineEvent(BaseModel):
    """A timeline event extracted from claim evidence."""

    event: str
    date_or_time: str
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="Exact evidence chunk IDs supporting this timeline event.")
    confidence: Literal["high", "medium", "low"]


class EvidenceInconsistency(BaseModel):
    """A potential inconsistency identified across claim evidence."""

    description: str
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="Exact evidence chunk IDs supporting this inconsistency.")
    explanation: str
    confidence: Literal["high", "medium", "low"]


class EvidenceAnalystOutput(BaseModel):
    """Structured claim evidence analysis produced by the Evidence Analyst."""

    summary: str
    factual_findings: list[ClaimEvidenceFinding] = Field(default_factory=list)
    timeline: list[ClaimTimelineEvent] = Field(default_factory=list)
    inconsistencies: list[EvidenceInconsistency] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    overall_assessment: Literal[
        "supportive",
        "contradictory",
        "mixed",
        "insufficient_evidence",
    ]
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


class SupervisorPlan(BaseModel):
    """Validated execution plan produced by the Supervisor."""

    selected_analysts: list[
        Literal[
            "intake_agent",
            "policy_analyst",
            "evidence_analyst",
            "repair_estimate_analyst",
            "risk_anomaly_agent",
        ]
    ] = Field(
        min_length=1,
        max_length=5,
        description=(
            "Specialist agents selected for this investigation. "
            "Only currently implemented specialists are permitted."
        ),
    )
    routing_rationale: str = Field(
        min_length=1,
        description="Brief explanation for the selected specialist agents.",
    )
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


class IntakeExtractedField(BaseModel):
    """A document field extracted with traceable evidence references."""

    field_name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    page_numbers: list[int] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    uncertain: bool = Field(
        default=False,
        description="Whether the extracted value is ambiguous or only partially readable.",
    )


class IntakeDocumentFlag(BaseModel):
    """A potential document quality or completeness issue."""

    description: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    severity: Literal["low", "medium", "high"]


class IntakeDocumentInventoryItem(BaseModel):
    """Inventory entry for an uploaded claim document."""

    filename: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    status: Literal["complete", "incomplete", "unreadable", "uncertain"]
    source_evidence_ids: list[str] = Field(min_length=1)


class IntakeDocumentOutput(BaseModel):
    """Structured document intake analysis."""

    summary: str
    extracted_fields: list[IntakeExtractedField] = Field(default_factory=list)
    document_flags: list[IntakeDocumentFlag] = Field(default_factory=list)
    document_inventory: list[IntakeDocumentInventoryItem] = Field(
        default_factory=list
    )
    missing_information: list[str] = Field(default_factory=list)
    overall_assessment: Literal[
        "documents_sufficient",
        "documents_incomplete",
        "insufficient_documents",
    ]
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


class RepairEstimateExtractedLineItem(BaseModel):
    """Source-extracted repair line item; amounts remain uncomputed text."""

    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    reported_amount: str | None = Field(
        default=None,
        description="Amount explicitly printed for this line, not a calculated value.",
    )
    source_evidence_ids: list[str] = Field(min_length=1)


class RepairEstimateClarificationNeed(BaseModel):
    """An estimate detail that needs clarification, grounded in source evidence."""

    question: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)


class RepairEstimateExtraction(BaseModel):
    """LLM extraction only; does not contain calculated totals."""

    line_items: list[RepairEstimateExtractedLineItem] = Field(
        default_factory=list
    )
    clarification_needs: list[RepairEstimateClarificationNeed] = Field(
        default_factory=list
    )
    missing_information: list[str] = Field(default_factory=list)
    extraction_complete: bool


class RepairEstimateSourceReference(BaseModel):
    """Canonical source provenance resolved from retrieved evidence."""

    evidence_id: str
    document_id: str
    filename: str
    page_number: int


class RepairEstimateLineItem(BaseModel):
    """Validated extracted estimate line and its canonical provenance."""

    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    reported_amount: str | None = None
    source_evidence_ids: list[str] = Field(min_length=1)
    sources: list[RepairEstimateSourceReference] = Field(min_length=1)
    item_category: Literal["part", "labor", "other"] = "part"
    normalized_quantity: int | None = None
    normalized_unit_price: Decimal | None = None
    normalized_reported_amount: Decimal | None = None
    currency: str | None = None
    quantity_status: Literal["extracted", "unavailable", "invalid"] = "extracted"
    value_status: Literal[
        "calculated",
        "reported_only_quantity_unavailable",
        "calculation_error",
        "unverified",
    ] = "calculated"


class RepairEstimateLineCalculation(BaseModel):
    """Deterministic calculation result for one extracted line."""

    line_item_index: int
    calculated_total: Decimal | None
    valid: bool


class RepairEstimateClarificationOutput(BaseModel):
    """Clarification question with canonical source provenance."""

    question: str
    source_evidence_ids: list[str] = Field(min_length=1)
    sources: list[RepairEstimateSourceReference] = Field(min_length=1)


class RepairEstimateFindingOutput(BaseModel):
    """Rules or extraction finding with canonical evidence provenance."""

    code: str
    description: str
    source_evidence_ids: list[str] = Field(min_length=1)
    sources: list[RepairEstimateSourceReference] = Field(min_length=1)
    line_item_indexes: list[int] = Field(default_factory=list)


class RepairEstimateAnalystOutput(BaseModel):
    """Repair estimate analysis separating extraction from calculations."""

    estimate_status: Literal["complete", "incomplete", "unavailable"]
    line_items: list[RepairEstimateLineItem] = Field(default_factory=list)
    line_calculations: list[RepairEstimateLineCalculation] = Field(
        default_factory=list
    )
    findings: list[RepairEstimateFindingOutput] = Field(default_factory=list)
    clarification_needs: list[RepairEstimateClarificationOutput] = Field(
        default_factory=list
    )
    missing_information: list[str] = Field(default_factory=list)
    valid_line_subtotal: Decimal | None = None
    complete_estimate_total: Decimal | None = None
    parts_subtotal: Decimal | None = None
    labor_subtotal: Decimal | None = None
    reported_line_items_subtotal: Decimal | None = None
    reported_gross_total: Decimal | None = None
    reported_depreciation_total: Decimal | None = None
    reported_deductible: Decimal | None = None
    reported_net_total: Decimal | None = None
    subtotal_reconciled: bool | None = None
    source_data_complete: bool
    calculation_complete: bool
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


class RiskAnomalyEvidenceQuote(BaseModel):
    """Verbatim source excerpt tied to a retrieved evidence ID."""

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=8)


class RiskAnomalyFindingExtraction(BaseModel):
    """Model-produced finding text and evidence IDs, without source metadata."""

    finding: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[RiskAnomalyEvidenceQuote] = Field(default_factory=list)


class RiskAnomalyExtraction(BaseModel):
    """Untrusted model extraction; provenance is added by application code."""

    observed_facts: list[RiskAnomalyFindingExtraction] = Field(
        default_factory=list
    )
    anomalies: list[RiskAnomalyFindingExtraction] = Field(default_factory=list)
    hypotheses: list[RiskAnomalyFindingExtraction] = Field(default_factory=list)
    missing_information: list[RiskAnomalyFindingExtraction] = Field(
        default_factory=list
    )


class RiskAnomalySourceReference(BaseModel):
    """Canonical source provenance resolved from retrieved evidence."""

    evidence_id: str
    document_id: str
    filename: str
    page_number: int


class RiskAnomalyFinding(BaseModel):
    """A cautious finding tied to canonical retrieved source provenance."""

    finding: str
    explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[RiskAnomalyEvidenceQuote] = Field(default_factory=list)
    sources: list[RiskAnomalySourceReference] = Field(default_factory=list)
    requires_human_verification: bool = Field(default=True, description='Always true; human verification is mandatory.')


class RiskAnomalyOutput(BaseModel):
    """Evidence-backed anomaly analysis, not a claim or fraud decision."""

    overall_status: Literal["analyzed", "insufficient_evidence"]
    observed_facts: list[RiskAnomalyFinding] = Field(default_factory=list)
    anomalies: list[RiskAnomalyFinding] = Field(default_factory=list)
    hypotheses: list[RiskAnomalyFinding] = Field(default_factory=list)
    missing_information: list[RiskAnomalyFinding] = Field(default_factory=list)
    human_review_required: bool = Field(default=True, description='Always true; human investigator review is mandatory.')


ReviewReportSpecialistName = Literal[
    "intake_agent",
    "evidence_analyst",
    "policy_analyst",
    "repair_estimate_analyst",
    "risk_anomaly_agent",
]

ReviewReportSpecialistStatus = Literal[
    "completed",
    "insufficient_evidence",
    "unavailable",
    "failed",
    "skipped",
    "pending",
]

ReviewReportSourceBasis = Literal[
    "retrieved_evidence",
    "analyst_output",
    "evidence_and_analyst_outputs",
]


class ReviewReportEvidenceChunk(BaseModel):
    """Canonical retrieved evidence supplied to the report agent."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        frozen=True,
    )

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    similarity: float | None = None
    embedding_model: str | None = None
    extraction_method: str | None = None
    ocr_confidence: float | None = None
    clause_id: str | None = None
    clause_identifier: str | None = None
    clause_category: str | None = None
    verification_status: str | None = None
    policy_version: str | None = None
    source_url: str | None = None
    insurer_name: str | None = None
    product_name: str | None = None
    policy_identifier: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None

    @field_validator("chunk_id", "document_id", "clause_id", mode="before")
    @classmethod
    def preserve_opaque_ids(cls, value: object) -> object:
        """Normalize UUID objects without interpreting evidence IDs."""

        return str(value) if isinstance(value, UUID) else value

    @field_validator(
        "chunk_id",
        "document_id",
        "filename",
        "text",
    )
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence metadata and text must not be blank.")
        return value

    @field_validator(
        "clause_identifier",
        "clause_category",
        "verification_status",
        "policy_version",
        "source_url",
        "insurer_name",
        "product_name",
        "policy_identifier",
        "effective_from",
        "effective_to",
    )
    @classmethod
    def reject_blank_optional_values(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Evidence metadata and text must not be blank.")
        return value


class ReviewReportSpecialistInput(BaseModel):
    """One specialist result with explicit execution status and limitations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReviewReportSpecialistStatus
    analysis: dict[str, object] | None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_and_analysis(self) -> "ReviewReportSpecialistInput":
        if self.status in {"completed", "insufficient_evidence"} and (
            self.analysis is None
        ):
            raise ValueError(
                "A completed or insufficient-evidence status must include "
                "its structured analysis."
            )
        if self.status not in {"completed", "insufficient_evidence"} and (
            self.analysis is not None
        ):
            raise ValueError(
                "Only completed or insufficient-evidence outputs may be included."
            )
        return self


class ReviewReportInput(BaseModel):
    """Trusted workflow snapshot for standalone investigation-report synthesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_facts: dict[str, object] | None
    retrieved_evidence: list[ReviewReportEvidenceChunk] = Field(
        default_factory=list
    )
    evidence_retrieval_status: Literal[
        "completed",
        "limited",
        "unavailable",
        "not_performed",
    ]
    evidence_retrieval_limitations: list[str] = Field(default_factory=list)
    intake_agent: ReviewReportSpecialistInput
    evidence_analyst: ReviewReportSpecialistInput
    policy_analyst: ReviewReportSpecialistInput
    repair_estimate_analyst: ReviewReportSpecialistInput
    risk_anomaly_agent: ReviewReportSpecialistInput
    structured_claim_context: dict[str, object] | None = None
    uploaded_documents: list[dict[str, object]] = Field(default_factory=list)
    specialist_evidence_usage: dict[str, list[str]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_retrieval_status(self) -> "ReviewReportInput":
        if (
            self.evidence_retrieval_status in {"unavailable", "not_performed"}
            and self.retrieved_evidence
        ):
            raise ValueError(
                "Evidence cannot be supplied when retrieval was unavailable "
                "or not performed."
            )
        return self


DocumentEvidenceStatus = Literal[
    "uploaded_not_retrieved",
    "retrieved",
    "partially_available",
    "retrieved_unverified",
    "verified",
    "not_provided",
    "not_applicable",
    "conflicting",
]

MissingInformationCategory = Literal[
    "uploaded_not_retrieved",
    "retrieved",
    "partially_available",
    "retrieved_unverified",
    "verified",
    "not_provided",
    "not_applicable",
    "conflicting",
    "not_retrieved",
]


class MissingInformationReconciliationItem(BaseModel):
    """Canonical reconciliation record for a reported missing-information item."""

    model_config = ConfigDict(extra="forbid")

    field_or_topic: str = Field(min_length=1, max_length=300)
    original_statement: str = Field(min_length=1, max_length=1000)
    originating_specialist: str | None = Field(default=None, max_length=100)
    reconciled_category: MissingInformationCategory
    available_in_sources: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    extracted_value: str | None = Field(default=None, max_length=500)
    retained_in_missing_information: bool = True
    reconciliation_note: str = Field(min_length=1, max_length=1000)
    human_review_required: bool = True


class ReportSourceInventoryItem(BaseModel):
    """Canonical source inventory entry for a document in the investigation."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=500)
    document_type: str = Field(min_length=1, max_length=120)
    document_status: DocumentEvidenceStatus = "retrieved_unverified"
    processing_status: Literal[
        "processed",
        "pending_review",
        "verified",
        "uploaded",
        "failed",
        "unknown",
    ] = "processed"
    retrieval_status: Literal[
        "retrieved",
        "specialist_retrieved",
        "uploaded_not_retrieved",
        "not_retrieved",
        "partially_available",
        "retrieved_unverified",
        "verified",
        "not_provided",
        "not_applicable",
        "conflicting",
    ] = "retrieved"
    used_by_specialists: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    citation_count: int = Field(default=0, ge=0)
    verification_status: str | None = Field(default=None, max_length=100)


class ReviewReportEvidenceQuote(BaseModel):
    """Verbatim excerpt required to support a report evidence citation."""

    model_config = _STRICT_SCHEMA_CONFIG

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=8)


class ReviewReportItemExtraction(BaseModel):
    """Untrusted model-generated report item without source metadata."""

    model_config = _STRICT_SCHEMA_CONFIG

    statement: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[ReviewReportEvidenceQuote] = Field(
        default_factory=list
    )
    analyst_output_references: list["ReviewReportAnalystOutputReference"] = Field(
        default_factory=list
    )
    conflicting_assertions: list[
        "ReviewReportConflictAssertionExtraction"
    ] = Field(default_factory=list)
    limitation: str | None = None


class ReviewReportAnalystOutputReference(BaseModel):
    """Exact JSON Pointer to a textual finding in a specialist output."""

    model_config = _STRICT_SCHEMA_CONFIG

    specialist: ReviewReportSpecialistName
    output_path: str = Field(min_length=2)
    finding_text: str = Field(min_length=1)


class ReviewReportConflictAssertionExtraction(BaseModel):
    """One source-faithful assertion in a proposed report conflict."""

    model_config = _STRICT_SCHEMA_CONFIG

    assertion: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence_id: str | None = None
    quote: str | None = None
    analyst_output_reference: ReviewReportAnalystOutputReference | None = None


class ReviewReportExtraction(BaseModel):
    """Model-produced report content; coverage and provenance are application-owned."""

    model_config = _STRICT_SCHEMA_CONFIG

    observed_facts: list[ReviewReportItemExtraction] = Field(
        default_factory=list
    )
    analyst_interpretations: list[ReviewReportItemExtraction] = Field(
        default_factory=list
    )
    hypotheses: list[ReviewReportItemExtraction] = Field(default_factory=list)
    conflicting_findings: list[ReviewReportItemExtraction] = Field(
        default_factory=list
    )
    missing_information: list[ReviewReportItemExtraction] = Field(
        default_factory=list
    )
class ReviewReportSourceReference(BaseModel):
    """Evidence provenance resolved only from the canonical input snapshot."""

    model_config = _STRICT_SCHEMA_CONFIG

    evidence_id: str
    document_id: str
    filename: str
    page_number: int = Field(ge=1)


class ReviewReportItem(BaseModel):
    """Auditable report item with separate evidence and analyst references."""

    model_config = _STRICT_SCHEMA_CONFIG

    statement: str
    explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[ReviewReportEvidenceQuote] = Field(
        default_factory=list
    )
    sources: list[ReviewReportSourceReference] = Field(default_factory=list)
    analyst_output_references: list[ReviewReportAnalystOutputReference] = Field(
        default_factory=list
    )
    conflicting_assertions: list["ReviewReportConflictAssertion"] = Field(
        default_factory=list
    )
    source_basis: ReviewReportSourceBasis
    limitation: str | None = None
    originating_specialist: str | None = None
    attribution_status: Literal[
        "verified",
        "unverified",
        "system_derived",
    ] = "verified"
    missing_category: MissingInformationCategory | None = None


class ReviewReportConflictAssertion(BaseModel):
    """A distinct assertion with its canonical evidence or analyst reference."""

    model_config = _STRICT_SCHEMA_CONFIG

    assertion: str
    subject: str
    attribute: str
    value: str
    source: ReviewReportSourceReference | None = None
    analyst_output_reference: ReviewReportAnalystOutputReference | None = None


class ReviewReportSpecialistCoverage(BaseModel):
    """Execution coverage for one specialist, kept separate from findings."""

    model_config = _STRICT_SCHEMA_CONFIG

    specialist: ReviewReportSpecialistName
    status: ReviewReportSpecialistStatus
    analysis_included: bool
    limitations: list[str] = Field(default_factory=list)


class ReviewReportOutput(BaseModel):
    """Structured investigation report for human review, never a claim decision."""

    model_config = _STRICT_SCHEMA_CONFIG

    overall_status: Literal[
        "completed",
        "incomplete",
        "insufficient_evidence",
    ]
    observed_facts: list[ReviewReportItem] = Field(default_factory=list)
    analyst_interpretations: list[ReviewReportItem] = Field(
        default_factory=list
    )
    hypotheses: list[ReviewReportItem] = Field(default_factory=list)
    conflicting_findings: list[ReviewReportItem] = Field(default_factory=list)
    missing_information: list[ReviewReportItem] = Field(default_factory=list)
    specialist_coverage: list[ReviewReportSpecialistCoverage]
    evidence_retrieval_status: Literal[
        "completed",
        "limited",
        "unavailable",
        "not_performed",
    ]
    evidence_retrieval_limitations: list[str] = Field(default_factory=list)
    evidence_scope_note: str
    human_review_required: bool = Field(
        default=True,
        description="Always true; human investigator review is mandatory.",
    )
    report_generation_mode: Literal[
        "ai_generated",
        "deterministic_fallback",
    ] = "ai_generated"
    report_completeness: Literal[
        "complete",
        "partial",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    report_validation_status: Literal[
        "validated",
        "validated_with_warnings",
        "flagged_for_human_review",
        "validation_failed",
        "not_validated",
    ] = "not_validated"
    policy_verification_status: Literal[
        "verified",
        "pending_review",
        "unverified",
        "not_retrieved",
        "not_applicable",
    ] = "not_applicable"
    source_inventory: list[ReportSourceInventoryItem] = Field(
        default_factory=list
    )
    missing_information_reconciliation: list[
        MissingInformationReconciliationItem
    ] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    validation_failures: list[str] = Field(default_factory=list)
