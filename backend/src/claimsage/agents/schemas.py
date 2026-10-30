"""Structured output schemas for ClaimSage specialist agents."""

from typing import Literal

from pydantic import BaseModel, Field


class PolicyClauseFinding(BaseModel):
    """A policy finding grounded in retrieved evidence."""

    finding: str = Field(
        description="A concise finding about a relevant policy provision."
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Exact evidence chunk IDs supporting this finding."
    )
    explanation: str = Field(
        description="Why the cited policy evidence matters to the investigation."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in the interpretation, not certainty of coverage."
    )


class PolicyAnalystOutput(BaseModel):
    """Structured policy analysis produced by the Policy Analyst."""

    summary: str = Field(
        description="Concise summary of the policy evidence relevant to the task."
    )
    relevant_clauses: list[PolicyClauseFinding] = Field(
        default_factory=list
    )
    coverage_indicators: list[str] = Field(
        default_factory=list,
        description="Policy provisions that may support coverage, without deciding it."
    )
    exclusions_and_conditions: list[str] = Field(
        default_factory=list,
        description="Relevant exclusions, limitations, conditions, and requirements."
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
    human_review_required: Literal[True] = True
