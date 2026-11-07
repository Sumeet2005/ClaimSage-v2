"""Synthetic, insert-only Motor and Health investigation demo fixtures."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class EvidenceFixture:
    """Synthetic evidence text rendered to a temporary PDF by the seed tool."""

    filename: str
    title: str
    text: str
    is_repair_estimate: bool = False


@dataclass(frozen=True, slots=True)
class PolicyFixture:
    """Official policy source with explicitly supported metadata."""

    source_url: str
    policy_identifier: str
    insurance_type: str
    policy_version: str
    effective_from: date | None
    insurer_name: str | None = None
    product_name: str | None = None
    effective_to: date | None = None
    applicability_note: str | None = None


@dataclass(frozen=True, slots=True)
class DemoScenario:
    """One synthetic claim and its shared-pipeline inputs."""

    claim_number: str
    claimant_name: str
    claim_type: str
    loss_date: date
    summary: str
    task: str
    policy: PolicyFixture
    evidence: tuple[EvidenceFixture, ...]


MOTOR_SCENARIO = DemoScenario(
    claim_number="CLM-SYNTH-MOTOR-001",
    claimant_name="Kavya Sample",
    claim_type="auto",
    loss_date=date(2025, 1, 15),
    summary=(
        "Synthetic motor claim for a fictional vehicle and claimant. "
        "The insurer's official product page and policy wording identify "
        "Private Car Base Package Policy UIN "
        "IRDAN190RP0042V01100001, but neither establishes its effective-from "
        "date. Policy applicability must remain unconfirmed."
    ),
    task=(
        "Compare the synthetic accident statement and repair estimate. "
        "Review policy wording only if an applicable version is established; "
        "identify explainable cross-source inconsistencies and evidence gaps "
        "for human review. Do not assign a risk score or make a claim decision."
    ),
    policy=PolicyFixture(
        source_url=(
            "https://www.newindia.co.in/assets/docs/know-more/motor/"
            "STANDARD%20FORM%20FOR%20PRIVATE%20CAR%20BASE%20PACKAGE%20POLICY.pdf"
        ),
        policy_identifier="DEMO-MOTOR-2025-001",
        insurance_type="auto",
        policy_version="IRDAN190RP0042V01100001",
        effective_from=None,
        applicability_note=(
            "The official New India Assurance product page lists Private Car "
            "Base Package Policy under UIN IRDAN190RP0042V01100001. The "
            "official six-page wording carries the same UIN and title but "
            "contains no effective-from date; its insurance period is stated "
            "in the individual policy schedule. The product listing does not "
            "establish applicability to this synthetic loss date. Do not "
            "infer an effective date from document metadata or UIN digits."
        ),
    ),
    evidence=(
        EvidenceFixture(
            filename="synthetic_motor_incident.pdf",
            title="Synthetic motor incident statement",
            text=(
                "SYNTHETIC DEMO EVIDENCE - no real claimant or vehicle data.\n"
                "Claim number: CLM-SYNTH-MOTOR-001.\n"
                "Fictional claimant: Kavya Sample.\n"
                "Fictional policy number: DEMO-MOTOR-2025-001.\n"
                "Fictional vehicle: MH-TEST-0001, a 2021 compact sedan.\n"
                "Reported loss date: 15 January 2025.\n"
                "Reported location: Pune, Maharashtra.\n"
                "The driver reports a low-speed collision with a stationary "
                "roadside barrier while parking. The front bumper and left "
                "headlamp were reported damaged. No injury is reported in "
                "this synthetic statement.\n"
                "This statement is unverified and is not an insurer decision."
            ),
        ),
        EvidenceFixture(
            filename="synthetic_motor_repair_estimate.pdf",
            title="Synthetic repair estimate",
            is_repair_estimate=True,
            text=(
                "SYNTHETIC DEMO EVIDENCE - no real repairer or vehicle data.\n"
                "Claim number: CLM-SYNTH-MOTOR-001.\n"
                "Estimate date: 20 January 2025.\n"
                "Fictional vehicle: MH-TEST-0001.\n"
                "Front bumper replacement: quantity 1, unit price INR 18500, "
                "reported amount INR 18500.\n"
                "Left headlamp assembly: quantity 1, unit price INR 12300, "
                "reported amount INR 12300.\n"
                "Paint and materials: quantity 1, unit price INR 8000, "
                "reported amount INR 8000.\n"
                "Labor: quantity 1, unit price INR 9500, "
                "reported amount INR 9500.\n"
                "Reported estimate total: INR 48300.\n"
                "This is a fictional estimate for deterministic calculation "
                "and human review; it is not an approval or settlement."
            ),
        ),
    ),
)


HEALTH_SCENARIO = DemoScenario(
    claim_number="CLM-SYNTH-HEALTH-001",
    claimant_name="Devika Example",
    claim_type="health",
    loss_date=date(2022, 6, 12),
    summary=(
        "Synthetic hospitalization claim for a fictional claimant. "
        "All medical and billing details are invented for demonstration."
    ),
    task=(
        "Compare the synthetic discharge summary and hospital bill with "
        "the retrieved policy wording for the loss date. Separate source "
        "facts from interpretation, identify explainable inconsistencies "
        "and information gaps for human review, and do not make a claim "
        "decision."
    ),
    policy=PolicyFixture(
        source_url=(
            "https://www.newindia.co.in/cms/"
            "b41ea7a9-66ff-47c3-94d4-4da93fde63d2/"
            "Policy%20Clause%20New%20India%20Mediclaim%20Policy%20"
            "wef%201st%20April%202021.pdf?guest=true"
        ),
        policy_identifier="DEMO-HEALTH-2022-001",
        insurance_type="health",
        policy_version="NIAHLIP21277V042021",
        effective_from=date(2021, 4, 1),
        insurer_name="New India Assurance",
        product_name="New India Mediclaim Policy",
    ),
    evidence=(
        EvidenceFixture(
            filename="synthetic_health_discharge_summary.pdf",
            title="Synthetic hospitalization discharge summary",
            text=(
                "SYNTHETIC DEMO EVIDENCE - no real patient or provider data.\n"
                "Claim number: CLM-SYNTH-HEALTH-001.\n"
                "Fictional claimant: Devika Example.\n"
                "Fictional policy number: DEMO-HEALTH-2022-001.\n"
                "Reported admission: 12 June 2022.\n"
                "Reported discharge: 15 June 2022.\n"
                "Fictional facility: Sample General Hospital, Pune.\n"
                "Fictional discharge diagnosis: acute appendicitis; "
                "laparoscopic appendectomy is recorded as performed.\n"
                "This synthetic summary does not establish medical necessity, "
                "policy coverage, or the authenticity of a real record."
            ),
        ),
        EvidenceFixture(
            filename="synthetic_health_itemized_bill.pdf",
            title="Synthetic itemized hospital bill",
            text=(
                "SYNTHETIC DEMO EVIDENCE - no real patient or provider data.\n"
                "Claim number: CLM-SYNTH-HEALTH-001.\n"
                "Fictional claimant: Devika Example.\n"
                "Fictional facility: Sample General Hospital, Pune.\n"
                "Admission: 12 June 2022; discharge: 15 June 2022.\n"
                "Room charges: 3 days x INR 4000 = INR 12000.\n"
                "Professional charges: 3 days x INR 1500 = INR 4500.\n"
                "Diagnostics: INR 8500.\n"
                "Procedure charges: INR 18000.\n"
                "Pharmacy: INR 21500.\n"
                "Reported total: INR 64500.\n"
                "This fictional bill is supplied for arithmetic and evidence "
                "consistency review only; it is not a real invoice."
            ),
        ),
    ),
)


DEMO_SCENARIOS = (MOTOR_SCENARIO, HEALTH_SCENARIO)
