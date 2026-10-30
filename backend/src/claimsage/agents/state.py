"""Typed state used by ClaimSage investigation workflows."""

from typing import TypedDict


class InvestigationState(TypedDict):
    """Shared state passed between investigation workflow nodes."""

    employee_id: str
    claim_id: str
    task: str
    claim_facts: dict[str, object] | None
    policy_evidence: list[dict[str, object]]
    policy_analysis: dict[str, object] | None
    ai_analysis_status: str | None
    result: dict[str, object] | None
    error: str | None
