"""Unit tests for the ClaimSage Evidence Analyst."""

from unittest.mock import MagicMock

import pytest

from claimsage.agents import evidence_analyst
from claimsage.agents.evidence_analyst import (
    EvidenceAnalystError,
    analyze_claim_evidence,
)
from claimsage.agents.schemas import (
    ClaimEvidenceFinding,
    ClaimTimelineEvent,
    EvidenceAnalystOutput,
    EvidenceInconsistency,
)


def make_evidence() -> list[dict[str, object]]:
    """Create synthetic retrieved claim evidence."""

    return [
        {
            "chunk_id": "claim-evidence-001",
            "document_id": "document-001",
            "filename": "synthetic_medical_report.pdf",
            "page_number": 2,
            "extraction_method": "native",
            "ocr_confidence": None,
            "text": "The synthetic patient was admitted on 12 March 2026.",
            "similarity": 0.94,
        },
        {
            "chunk_id": "claim-evidence-002",
            "document_id": "document-002",
            "filename": "synthetic_discharge_summary.pdf",
            "page_number": 3,
            "extraction_method": "ocr",
            "ocr_confidence": 96.5,
            "text": "The synthetic discharge date is 18 March 2026.",
            "similarity": 0.91,
        },
    ]


def make_analysis(
    *,
    evidence_ids: list[str] | None = None,
) -> EvidenceAnalystOutput:
    """Create a valid structured Evidence Analyst response."""

    supporting_ids = (
        evidence_ids
        if evidence_ids is not None
        else ["claim-evidence-001"]
    )

    return EvidenceAnalystOutput(
        summary="The supplied documents describe a synthetic hospitalization.",
        factual_findings=[
            ClaimEvidenceFinding(
                finding="The patient was admitted on 12 March 2026.",
                supporting_evidence_ids=supporting_ids,
                explanation="The medical report explicitly states the admission date.",
                confidence="high",
            )
        ],
        timeline=[
            ClaimTimelineEvent(
                event="Hospital admission",
                date_or_time="12 March 2026",
                supporting_evidence_ids=["claim-evidence-001"],
                confidence="high",
            )
        ],
        inconsistencies=[
            EvidenceInconsistency(
                description="The documents require review for date consistency.",
                supporting_evidence_ids=[
                    "claim-evidence-001",
                    "claim-evidence-002",
                ],
                explanation="The passages contain dates relevant to the same hospitalization.",
                confidence="low",
            )
        ],
        missing_information=[
            "The complete treatment record has not been supplied."
        ],
        evidence_gaps=[
            "Additional supporting medical records may be required."
        ],
        overall_assessment="supportive",
        human_review_required=True,
    )


def make_model_mock(response: EvidenceAnalystOutput) -> MagicMock:
    """Create a mock structured-output model."""

    structured_model = MagicMock()
    structured_model.invoke.return_value = response

    model = MagicMock()
    model.with_structured_output.return_value = structured_model

    return model


def test_valid_evidence_analysis_returns_structured_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid findings and citations are accepted."""

    model = make_model_mock(make_analysis())

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        lambda: model,
    )

    result = analyze_claim_evidence(
        task="Review the synthetic hospitalization evidence.",
        claim_evidence=make_evidence(),
    )

    assert isinstance(result, EvidenceAnalystOutput)
    assert result.human_review_required is True
    assert len(result.factual_findings) == 1
    assert len(result.timeline) == 1
    assert len(result.inconsistencies) == 1
    assert result.factual_findings[0].supporting_evidence_ids == [
        "claim-evidence-001"
    ]

    model.with_structured_output.assert_called_once()


def test_empty_evidence_returns_insufficient_result_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty evidence does not invoke the language model."""

    model = MagicMock()

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        lambda: model,
    )

    result = analyze_claim_evidence(
        task="Review the synthetic hospitalization evidence.",
        claim_evidence=[],
    )

    assert result.overall_assessment == "insufficient_evidence"
    assert result.factual_findings == []
    assert result.timeline == []
    assert result.inconsistencies == []
    assert result.human_review_required is True

    model.with_structured_output.assert_not_called()


@pytest.mark.parametrize(
    "finding_type",
    ["factual", "timeline", "inconsistency"],
)
def test_unknown_evidence_reference_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    finding_type: str,
) -> None:
    """Every specialist finding must reference retrieved evidence."""

    analysis = make_analysis()

    if finding_type == "factual":
        analysis.factual_findings[0].supporting_evidence_ids = [
            "fabricated-evidence-999"
        ]
    elif finding_type == "timeline":
        analysis.timeline[0].supporting_evidence_ids = [
            "fabricated-evidence-999"
        ]
    else:
        analysis.inconsistencies[0].supporting_evidence_ids = [
            "fabricated-evidence-999"
        ]

    model = make_model_mock(analysis)

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        lambda: model,
    )

    with pytest.raises(
        EvidenceAnalystError,
        match="not retrieved",
    ):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=make_evidence(),
        )


@pytest.mark.parametrize(
    "finding_type",
    ["factual", "timeline", "inconsistency"],
)
def test_finding_without_citations_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    finding_type: str,
) -> None:
    """Every factual finding, event, and inconsistency needs citations."""

    analysis = make_analysis()

    if finding_type == "factual":
        analysis.factual_findings[0].supporting_evidence_ids = []
    elif finding_type == "timeline":
        analysis.timeline[0].supporting_evidence_ids = []
    else:
        analysis.inconsistencies[0].supporting_evidence_ids = []

    model = make_model_mock(analysis)

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        lambda: model,
    )

    with pytest.raises(
        EvidenceAnalystError,
        match="without supporting citations",
    ):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=make_evidence(),
        )


def test_duplicate_evidence_ids_are_rejected() -> None:
    """Duplicate retrieved IDs are rejected before model invocation."""

    evidence = make_evidence()
    evidence.append(evidence[0].copy())

    with pytest.raises(
        EvidenceAnalystError,
        match="duplicate evidence IDs",
    ):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=evidence,
        )


@pytest.mark.parametrize(
    "evidence",
    [
        [{"chunk_id": "", "text": "Synthetic evidence."}],
        [{"chunk_id": "evidence-001", "text": ""}],
        [{"chunk_id": "evidence-001", "text": "   "}],
        ["not a dictionary"],
    ],
)
def test_invalid_retrieved_evidence_is_rejected(
    evidence: list[dict[str, object]],
) -> None:
    """Malformed retrieved evidence cannot reach the language model."""

    with pytest.raises(EvidenceAnalystError):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=evidence,
        )


@pytest.mark.parametrize(
    "task",
    ["", "   "],
)
def test_empty_investigation_task_is_rejected(task: str) -> None:
    """An empty investigation task is invalid."""

    with pytest.raises(ValueError, match="non-empty"):
        analyze_claim_evidence(
            task=task,
            claim_evidence=make_evidence(),
        )


def test_non_list_evidence_is_rejected() -> None:
    """Evidence input must be a list."""

    with pytest.raises(ValueError, match="list"):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=None,  # type: ignore[arg-type]
        )


def test_llm_failure_returns_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failures are wrapped in a controlled specialist error."""

    def fail_to_initialize() -> MagicMock:
        raise RuntimeError("Synthetic provider failure.")

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        fail_to_initialize,
    )

    with pytest.raises(
        EvidenceAnalystError,
        match="could not complete",
    ):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=make_evidence(),
        )


def test_invalid_structured_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected model response types are rejected."""

    model = MagicMock()
    structured_model = MagicMock()
    structured_model.invoke.return_value = {"summary": "Invalid response"}
    model.with_structured_output.return_value = structured_model

    monkeypatch.setattr(
        evidence_analyst,
        "get_chat_model",
        lambda: model,
    )

    with pytest.raises(
        EvidenceAnalystError,
        match="invalid structured response",
    ):
        analyze_claim_evidence(
            task="Review the synthetic hospitalization evidence.",
            claim_evidence=make_evidence(),
        )
