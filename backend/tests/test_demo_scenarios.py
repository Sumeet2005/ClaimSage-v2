"""Pure unit checks for synthetic Motor and Health demo fixtures."""

from datetime import date
from uuid import uuid4

from claimsage.demo_scenarios import DEMO_SCENARIOS, HEALTH_SCENARIO
from claimsage.schemas.agent import InvestigationRequest
from scripts.seed_investigation_scenarios import SCENARIOS_TO_SEED


def test_scenario_fixtures_cover_auto_and_health_without_real_data() -> None:
    by_type = {scenario.claim_type: scenario for scenario in DEMO_SCENARIOS}

    assert set(by_type) == {"auto", "health"}
    assert all(
        scenario.claim_number.startswith("CLM-SYNTH-")
        for scenario in DEMO_SCENARIOS
    )
    assert all(
        "SYNTHETIC DEMO EVIDENCE" in evidence.text
        for scenario in DEMO_SCENARIOS
        for evidence in scenario.evidence
    )

    motor = by_type["auto"]
    assert motor.policy.policy_identifier == "DEMO-MOTOR-2025-001"
    assert motor.policy.policy_version == "IRDAN190RP0042V01100001"
    assert motor.policy.effective_from is None
    assert motor.policy.source_url.startswith("https://www.newindia.co.in/")
    assert motor.policy.applicability_note is not None
    assert "does not establish applicability" in motor.policy.applicability_note
    assert sum(e.is_repair_estimate for e in motor.evidence) == 1

    health = by_type["health"]
    assert health.policy.policy_identifier == "DEMO-HEALTH-2022-001"
    assert health.policy.policy_version == "NIAHLIP21277V042021"
    assert health.policy.effective_from == date(2021, 4, 1)
    assert health.policy.insurer_name == "New India Assurance"
    assert health.policy.product_name == "New India Mediclaim Policy"
    assert health.policy.source_url.startswith("https://www.newindia.co.in/")
    assert all(
        not evidence.is_repair_estimate for evidence in health.evidence
    )


def test_scenario_seed_is_limited_to_health() -> None:
    assert SCENARIOS_TO_SEED == (HEALTH_SCENARIO,)


def test_investigation_request_accepts_repair_estimate_reference() -> None:
    estimate_id = uuid4()
    request = InvestigationRequest(
        claim_id=uuid4(),
        task="Review the synthetic repair estimate.",
        repair_estimate_document_id=estimate_id,
    )

    assert request.repair_estimate_document_id == estimate_id
