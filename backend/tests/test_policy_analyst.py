"""Unit tests for the ClaimSage Policy Analyst."""

from unittest.mock import MagicMock

import pytest

from claimsage.agents import policy_analyst
from claimsage.agents.policy_analyst import (
    PolicyAnalystError,
    analyze_policy,
)
from claimsage.agents.schemas import (
    PolicyAnalystOutput,
    PolicyClauseFinding,
)


def make_evidence() -> list[dict[str, object]]:
    """Create synthetic retrieved policy evidence."""
    return [
        {
            "chunk_id": "evidence-001",
            "document_id": "document-001",
            "filename": "synthetic_policy.pdf",
            "page_number": 4,
            "text": "Eligible hospitalization expenses are covered.",
            "similarity": 0.91,
        }
    ]


def make_analysis(
    *,
    evidence_ids: list[str] | None = None,
) -> PolicyAnalystOutput:
    """Create a valid structured analyst response."""
    return PolicyAnalystOutput(
        summary="The retrieved clause describes hospitalization coverage.",
        relevant_clauses=[
            PolicyClauseFinding(
                finding="Hospitalization expenses may be eligible.",
                supporting_evidence_ids=(
                    evidence_ids if evidence_ids is not None else ["evidence-001"]
                ),
                explanation=(
                    "The retrieved passage explicitly mentions eligible "
                    "hospitalization expenses."
                ),
                confidence="high",
            )
        ],
        coverage_indicators=[
            "The policy passage mentions eligible hospitalization expenses."
        ],
        exclusions_and_conditions=[],
        missing_information=[
            "The applicable policy limits have not been established."
        ],
        evidence_gaps=[
            "Additional policy provisions may be relevant."
        ],
        overall_assessment="potentially_supportive",
        human_review_required=True,
    )


def make_model_mock(response: PolicyAnalystOutput) -> MagicMock:
    """Create a mock structured-output model."""
    structured_model = MagicMock()
    structured_model.invoke.return_value = response

    model = MagicMock()
    model.with_structured_output.return_value = structured_model

    return model


def test_valid_policy_analysis_returns_structured_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid findings with retrieved evidence references are accepted."""
    model = make_model_mock(make_analysis())

    monkeypatch.setattr(
        policy_analyst,
        "get_chat_model",
        lambda: model,
    )

    result = analyze_policy(
        task="Investigate hospitalization coverage.",
        policy_evidence=make_evidence(),
    )

    assert isinstance(result, PolicyAnalystOutput)
    assert result.overall_assessment == "potentially_supportive"
    assert result.human_review_required is True
    assert result.relevant_clauses[0].supporting_evidence_ids == [
        "evidence-001"
    ]

    model.with_structured_output.assert_called_once()


def test_empty_policy_evidence_does_not_call_groq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No retrieved evidence produces an insufficient-evidence result."""
    model = MagicMock()

    monkeypatch.setattr(
        policy_analyst,
        "get_chat_model",
        lambda: model,
    )

    result = analyze_policy(
        task="Investigate hospitalization coverage.",
        policy_evidence=[],
    )

    assert result.overall_assessment == "insufficient_evidence"
    assert result.relevant_clauses == []
    assert result.human_review_required is True

    model.with_structured_output.assert_not_called()


def test_unknown_evidence_reference_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The analyst cannot cite evidence that was not retrieved."""
    model = make_model_mock(
        make_analysis(evidence_ids=["fabricated-evidence-999"])
    )

    monkeypatch.setattr(
        policy_analyst,
        "get_chat_model",
        lambda: model,
    )

    with pytest.raises(
        PolicyAnalystError,
        match="not retrieved",
    ):
        analyze_policy(
            task="Investigate hospitalization coverage.",
            policy_evidence=make_evidence(),
        )


def test_finding_without_citations_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every relevant clause finding must cite supporting evidence."""
    model = make_model_mock(make_analysis(evidence_ids=[]))

    monkeypatch.setattr(
        policy_analyst,
        "get_chat_model",
        lambda: model,
    )

    with pytest.raises(
        PolicyAnalystError,
        match="without supporting evidence",
    ):
        analyze_policy(
            task="Investigate hospitalization coverage.",
            policy_evidence=make_evidence(),
        )


def test_groq_failure_returns_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failures are wrapped in a controlled specialist error."""
    def fail_to_initialize() -> MagicMock:
        raise RuntimeError("Synthetic provider failure.")

    monkeypatch.setattr(
        policy_analyst,
        "get_chat_model",
        fail_to_initialize,
    )

    with pytest.raises(
        PolicyAnalystError,
        match="could not complete",
    ):
        analyze_policy(
            task="Investigate hospitalization coverage.",
            policy_evidence=make_evidence(),
        )
