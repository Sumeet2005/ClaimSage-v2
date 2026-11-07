"""Unit tests for the ClaimSage Supervisor agent."""

import json
from unittest.mock import MagicMock

import pytest

from claimsage.agents import supervisor as supervisor_module
from claimsage.agents.schemas import SupervisorPlan
from claimsage.agents.supervisor import (
    SupervisorError,
    create_supervisor_plan,
)

DEFAULT_ANALYSTS = [
    "policy_analyst",
    "evidence_analyst",
]


def make_plan(
    selected_analysts=None,
    routing_rationale="Both policy and claim evidence are relevant.",
):
    """Create a synthetic Supervisor plan."""
    if selected_analysts is None:
        selected_analysts = list(DEFAULT_ANALYSTS)

    return SupervisorPlan(
        selected_analysts=selected_analysts,
        routing_rationale=routing_rationale,
        human_review_required=True,
    )


def setup_supervisor(monkeypatch, response):
    """Mock the structured LLM response."""
    structured_model = MagicMock()
    structured_model.invoke.return_value = response

    model = MagicMock()
    model.with_structured_output.return_value = structured_model

    monkeypatch.setattr(
        supervisor_module,
        "get_chat_model",
        MagicMock(return_value=model),
    )

    return model, structured_model


def create_plan(**overrides):
    """Call the Supervisor with valid default execution context."""
    context = {
        "task": "Investigate this claim.",
        "claim_facts_available": True,
        "policy_evidence_available": True,
        "available_analysts": list(DEFAULT_ANALYSTS),
    }
    context.update(overrides)

    return create_supervisor_plan(**context)


def test_supervisor_returns_both_specialists(monkeypatch):
    """A cross-domain task can select both specialists."""
    plan = make_plan()
    model, structured_model = setup_supervisor(monkeypatch, plan)

    result = create_plan(
        task="Compare hospitalization records against policy conditions."
    )

    assert result == plan
    assert result.selected_analysts == DEFAULT_ANALYSTS
    assert result.human_review_required is True

    model.with_structured_output.assert_called_once_with(
        SupervisorPlan,
        method="function_calling",
    )
    structured_model.invoke.assert_called_once()


def test_supervisor_can_select_policy_analyst_only(monkeypatch):
    """Policy-specific tasks can select the Policy Analyst."""
    plan = make_plan(["policy_analyst"])
    setup_supervisor(monkeypatch, plan)

    result = create_plan(
        task="Review policy exclusions and applicable limits."
    )

    assert result.selected_analysts == ["policy_analyst"]


def test_supervisor_can_select_evidence_analyst_only(monkeypatch):
    """Document-specific tasks can select the Evidence Analyst."""
    plan = make_plan(["evidence_analyst"])
    setup_supervisor(monkeypatch, plan)

    result = create_plan(
        task="Build a timeline from uploaded hospitalization records."
    )

    assert result.selected_analysts == ["evidence_analyst"]


def test_supervisor_can_select_repair_estimate_analyst(monkeypatch):
    """Estimate review is selectable when trusted document evidence exists."""
    plan = make_plan(["repair_estimate_analyst"])
    setup_supervisor(monkeypatch, plan)

    result = create_plan(
        task="Review the repair estimate line items.",
        available_analysts=["repair_estimate_analyst"],
    )

    assert result.selected_analysts == ["repair_estimate_analyst"]
    assert result.human_review_required is True


def test_supervisor_can_select_risk_anomaly_agent_when_available(monkeypatch):
    """Risk analysis is selectable only from the trusted allowlist context."""
    plan = make_plan(["risk_anomaly_agent"])
    setup_supervisor(monkeypatch, plan)

    result = create_plan(
        task="Compare claim facts with retrieved records.",
        available_analysts=["risk_anomaly_agent"],
    )

    assert result.selected_analysts == ["risk_anomaly_agent"]
    assert result.human_review_required is True


def test_supervisor_rejects_risk_agent_when_not_available(monkeypatch):
    """The model cannot select Risk analysis absent from available analysts."""
    plan = make_plan(["risk_anomaly_agent"])
    setup_supervisor(monkeypatch, plan)

    with pytest.raises(SupervisorError, match="unavailable specialist"):
        create_plan(
            available_analysts=["evidence_analyst"],
        )


def test_supervisor_receives_execution_context(monkeypatch):
    """The LLM must receive trusted availability metadata."""
    plan = make_plan(["evidence_analyst"])
    _, structured_model = setup_supervisor(monkeypatch, plan)

    create_plan(
        task="Build a claim event timeline.",
        claim_facts_available=True,
        policy_evidence_available=False,
        available_analysts=["evidence_analyst"],
    )

    messages = structured_model.invoke.call_args.args[0]
    context = json.loads(messages[1][1])

    assert context == {
        "task": "Build a claim event timeline.",
        "claim_facts_available": True,
        "policy_evidence_available": False,
        "available_analysts": ["evidence_analyst"],
    }


@pytest.mark.parametrize("task", ["", "   ", None, 123])
def test_supervisor_rejects_invalid_task(task):
    """Invalid tasks must not invoke the LLM."""
    with pytest.raises(ValueError):
        create_plan(task=task)


@pytest.mark.parametrize(
    "claim_facts_available",
    ["yes", 1, None],
)
def test_supervisor_rejects_invalid_claim_availability(
    claim_facts_available,
):
    """Claim availability must be a boolean."""
    with pytest.raises(ValueError):
        create_plan(claim_facts_available=claim_facts_available)


@pytest.mark.parametrize(
    "policy_evidence_available",
    ["yes", 1, None],
)
def test_supervisor_rejects_invalid_policy_availability(
    policy_evidence_available,
):
    """Policy availability must be a boolean."""
    with pytest.raises(ValueError):
        create_plan(policy_evidence_available=policy_evidence_available)


@pytest.mark.parametrize(
    "available_analysts",
    [
        [],
        ["evidence_analyst", "evidence_analyst"],
        ["fraud_analyst"],
    ],
)
def test_supervisor_rejects_invalid_available_analysts(
    available_analysts,
):
    """Only unique, supported available specialists are accepted."""
    with pytest.raises(ValueError):
        create_plan(available_analysts=available_analysts)


def test_supervisor_wraps_provider_failure(monkeypatch):
    """Provider failures must become a safe Supervisor error."""
    model = MagicMock()
    model.with_structured_output.side_effect = RuntimeError(
        "Synthetic provider failure."
    )

    monkeypatch.setattr(
        supervisor_module,
        "get_chat_model",
        MagicMock(return_value=model),
    )

    with pytest.raises(SupervisorError):
        create_plan()


def test_supervisor_rejects_invalid_structured_response(monkeypatch):
    """Unexpected response types must be rejected."""
    setup_supervisor(
        monkeypatch,
        {"selected_analysts": ["policy_analyst"]},
    )

    with pytest.raises(SupervisorError):
        create_plan()


def test_supervisor_rejects_unavailable_specialist(monkeypatch):
    """The Supervisor cannot select a specialist absent from its allowlist."""
    plan = make_plan(["policy_analyst"])
    setup_supervisor(monkeypatch, plan)

    with pytest.raises(SupervisorError):
        create_plan(
            policy_evidence_available=False,
            available_analysts=["evidence_analyst"],
        )


def test_supervisor_rejects_duplicate_agents(monkeypatch):
    """Duplicate specialist selections must not be accepted."""
    plan = make_plan(
        ["policy_analyst", "policy_analyst"]
    )
    setup_supervisor(monkeypatch, plan)

    with pytest.raises(SupervisorError):
        create_plan()


def test_supervisor_schema_rejects_unsupported_agent():
    """The schema must reject agents outside the allowlist."""
    with pytest.raises(ValueError):
        SupervisorPlan(
            selected_analysts=["fraud_analyst"],
            routing_rationale="Unsupported agent.",
            human_review_required=True,
        )


def test_supervisor_schema_rejects_empty_agent_list():
    """The schema must require at least one specialist."""
    with pytest.raises(ValueError):
        SupervisorPlan(
            selected_analysts=[],
            routing_rationale="No specialist selected.",
            human_review_required=True,
        )
