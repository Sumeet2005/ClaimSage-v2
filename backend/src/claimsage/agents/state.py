"""Typed state used by ClaimSage investigation workflows."""

from typing import Literal, NotRequired, TypedDict

from claimsage.agents.schemas import ReviewReportOutput


class InvestigationState(TypedDict):
    """Shared state passed between investigation workflow nodes."""

    employee_id: str
    claim_id: str
    task: str

    claim_facts: dict[str, object] | None

    policy_evidence: list[dict[str, object]]
    policy_retrieval_status: str | None
    policy_analysis: dict[str, object] | None
    policy_analysis_status: NotRequired[str | None]

    claim_evidence: list[dict[str, object]]
    claim_evidence_retrieval_status: str | None
    intake_analysis: dict[str, object] | None
    intake_analysis_status: str | None
    evidence_analysis: dict[str, object] | None
    evidence_analysis_status: str | None
    repair_estimate_document_id: str | None
    repair_estimate_evidence: list[dict[str, object]]
    repair_estimate_analysis: dict[str, object] | None
    repair_estimate_analysis_status: str | None
    risk_analysis: dict[str, object] | None
    risk_analysis_status: str | None

    selected_analysts: list[str]
    supervisor_plan: dict[str, object] | None
    supervisor_status: str | None

    ai_analysis_status: str | None
    review_report: ReviewReportOutput | None
    review_report_status: Literal[
        "pending",
        "completed",
        "incomplete",
        "unavailable",
        "failed",
        "skipped",
    ]
    result: dict[str, object] | None
    error: str | None