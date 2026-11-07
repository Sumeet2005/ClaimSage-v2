"""LLM-powered Supervisor for controlled ClaimSage agent orchestration."""

import json

from claimsage.agents.llm import get_chat_model, invoke_structured
from claimsage.agents.schemas import SupervisorPlan


class SupervisorError(Exception):
    """Raised when the Supervisor cannot produce a safe execution plan."""


AVAILABLE_ANALYSTS = (
    "policy_analyst",
    "evidence_analyst",
    "intake_agent",
    "repair_estimate_analyst",
    "risk_anomaly_agent",
)


SYSTEM_PROMPT = """
You are the Supervisor of ClaimSage, an AI insurance claims
investigation assistant.

YOUR RESPONSIBILITIES:
1. Understand the investigation task.
2. Review the availability metadata supplied with the task.
3. Select only the specialist agents required for the investigation.
4. Explain your routing decision briefly.

AVAILABLE SPECIALISTS:

- policy_analyst:
  Analyzes authorized insurance policy passages, clauses,
  exclusions, conditions, and policy-related evidence gaps.

- evidence_analyst:
  Analyzes authorized claim documents, factual findings,
  event timelines, inconsistencies, and claim evidence gaps.

- intake_agent:
  Extracts structured fields from authorized claim documents, creates a
  document inventory, and flags document quality or completeness issues.

- repair_estimate_analyst:
  Extracts repair estimate line items, calculates totals deterministically,
  and flags duplicates or clarification needs for human review.

- risk_anomaly_agent:
  Compares authorized claim facts and retrieved claim evidence with completed
  analyst outputs to identify cited inconsistencies and information gaps for
  human review. It does not assign risk scores or make claim decisions.

ROUTING RULES:
- Select intake_agent when the task requires document intake, field
  extraction, document inventory, or document quality review.
- Select repair_estimate_analyst only when an authorized repair estimate
  document is available and the task requires estimate line-item review.
- Select risk_anomaly_agent only when authorized claim facts and retrieved
  claim evidence are available and the task requires cross-source comparison,
  inconsistency review, or evidence-gap analysis.
- Select policy_analyst when the task requires policy wording,
  coverage provisions, exclusions, limits, or conditions.
- Select evidence_analyst when the task requires examination
  of claim documents, factual events, timelines, or inconsistencies.
- Select policy_analyst and the relevant claim-evidence specialist when the
  task requires comparing claim facts with relevant policy provisions.
- Select only agents included in the available analyst list.
- Never select an unavailable specialist.
- Do not invent retrieved evidence or specialist capabilities.
- Repair-estimate anomalies are review flags, not findings of fraud or
  overcharging. The analyst does not determine coverage or liability.
- Availability metadata describes what is available before
  specialist execution; do not assume retrieval succeeded.

DECISION BOUNDARIES:
- You coordinate the workflow; you do not investigate evidence yourself.
- Never approve or deny a claim.
- Never determine final coverage, fraud, liability, or settlement.
- Never bypass authorization or access-control rules.
- Human investigator review is always required.

OUTPUT:
Return only structured output matching the supplied SupervisorPlan schema.
"""


def create_supervisor_plan(
    *,
    task: str,
    claim_facts_available: bool,
    policy_evidence_available: bool,
    available_analysts: list[str],
) -> SupervisorPlan:
    """Create a context-aware, validated specialist execution plan."""

    if not isinstance(task, str) or not task.strip():
        raise ValueError("A non-empty investigation task is required.")

    if not isinstance(claim_facts_available, bool):
        raise ValueError("Claim facts availability must be a boolean.")

    if not isinstance(policy_evidence_available, bool):
        raise ValueError("Policy evidence availability must be a boolean.")

    if not isinstance(available_analysts, list) or not available_analysts:
        raise ValueError("At least one available analyst is required.")

    if len(available_analysts) != len(set(available_analysts)):
        raise ValueError("Available analysts must not contain duplicates.")

    if not set(available_analysts).issubset(AVAILABLE_ANALYSTS):
        raise ValueError("An unsupported analyst was marked as available.")

    context = {
        "task": task.strip(),
        "claim_facts_available": claim_facts_available,
        "policy_evidence_available": policy_evidence_available,
        "available_analysts": available_analysts,
    }

    try:
        model = get_chat_model()
        structured_model = model.with_structured_output(
            SupervisorPlan,
            method="function_calling",
        )

        plan = invoke_structured(
            structured_model,
            messages=[
                ("system", SYSTEM_PROMPT),
                ("human", json.dumps(context)),
            ],
            output_schema=SupervisorPlan,
            stage="supervisor",
        )

    except Exception as exc:
        raise SupervisorError("The Supervisor could not create an execution plan.") from exc

    if not isinstance(plan, SupervisorPlan):
        raise SupervisorError("The Supervisor returned an invalid structured response.")

    if not plan.selected_analysts:
        raise SupervisorError("The Supervisor returned an empty execution plan.")

    if len(plan.selected_analysts) != len(set(plan.selected_analysts)):
        raise SupervisorError("The Supervisor returned duplicate specialist agents.")

    if not set(plan.selected_analysts).issubset(available_analysts):
        raise SupervisorError("The Supervisor selected an unavailable specialist.")

    plan.human_review_required = True

    return plan
