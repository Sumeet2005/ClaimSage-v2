"""Unit and graph integration tests for the Intake & Document Agent."""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import intake_agent
from claimsage.agents.graph import run_investigation
from claimsage.agents.intake_agent import (
    IntakeAgentError,
    analyze_claim_documents,
)
from claimsage.agents.schemas import (
    IntakeDocumentFlag,
    IntakeDocumentInventoryItem,
    IntakeDocumentOutput,
    IntakeExtractedField,
    ReviewReportOutput,
    SupervisorPlan,
)
from claimsage.agents.supervisor import (
    create_supervisor_plan,
)
from claimsage.rag.evidence_retrieval_service import RetrievedEvidenceChunk


@pytest.fixture(autouse=True)
def mock_review_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            return_value=ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="not_performed",
                evidence_scope_note="Synthetic report for intake tests.",
                human_review_required=True,
            )
        ),
    )


def make_evidence(
    *,
    chunk_id=None,
    filename="synthetic_claim.pdf",
    page_number=2,
    text="Date of service: 2026-03-14. Total amount: $125.00.",
):
    """Create one synthetic retrieved evidence dictionary."""
    return {
        "chunk_id": chunk_id or uuid4(),
        "document_id": uuid4(),
        "filename": filename,
        "page_number": page_number,
        "chunk_index": 0,
        "text": text,
        "similarity": 0.91,
        "embedding_model": "synthetic-model",
        "extraction_method": "native",
        "ocr_confidence": None,
    }


def make_retrieved_chunk(*, chunk_id=None) -> RetrievedEvidenceChunk:
    """Create a synthetic result matching the retrieval service dataclass."""
    return RetrievedEvidenceChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        filename="synthetic_claim.pdf",
        page_number=2,
        chunk_index=0,
        text="Date of service: 2026-03-14. Total amount: $125.00.",
        similarity=0.91,
        embedding_model="synthetic-model",
        extraction_method="ocr",
        ocr_confidence=96.5,
    )


def make_intake_output(
    evidence_ids: list[str] | None = None,
) -> IntakeDocumentOutput:
    """Build a valid synthetic structured Intake result."""
    ids = evidence_ids or ["synthetic-evidence-id"]
    return IntakeDocumentOutput(
        summary="The retrieved claim document contains a service date and amount.",
        extracted_fields=[
            IntakeExtractedField(
                field_name="date_of_service",
                value="2026-03-14",
                source_evidence_ids=[ids[0]],
                page_numbers=[2],
                confidence="high",
                uncertain=False,
            )
        ],
        document_flags=[
            IntakeDocumentFlag(
                description="The retrieved excerpt does not show a provider signature.",
                source_evidence_ids=[ids[0]],
                severity="low",
            )
        ],
        document_inventory=[
            IntakeDocumentInventoryItem(
                filename="synthetic_claim.pdf",
                document_type="Claim invoice",
                status="complete",
                source_evidence_ids=ids,
            )
        ],
        missing_information=[],
        overall_assessment="documents_sufficient",
        human_review_required=True,
    )


def setup_intake_model(monkeypatch, response):
    """Mock both the chat model and its structured-output wrapper."""
    structured_model = MagicMock()
    structured_model.invoke.return_value = response
    model = MagicMock()
    model.with_structured_output.return_value = structured_model
    monkeypatch.setattr(intake_agent, "get_chat_model", lambda: model)
    return model, structured_model


def test_empty_evidence_returns_insufficient_result_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty retrieval is handled without initializing the LLM."""
    get_model = MagicMock()
    monkeypatch.setattr(intake_agent, "get_chat_model", get_model)

    result = analyze_claim_documents(
        task="Extract claim invoice details.",
        claim_evidence=[],
    )

    assert result.overall_assessment == "insufficient_documents"
    assert result.document_inventory == []
    assert result.human_review_required is True
    get_model.assert_not_called()


def test_valid_structured_extraction_preserves_citations_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid extracted fields, flags, and inventory are returned as structured data."""
    evidence_id = uuid4()
    evidence = make_evidence(chunk_id=evidence_id)
    response = make_intake_output([str(evidence_id)])
    model, structured_model = setup_intake_model(monkeypatch, response)

    result = analyze_claim_documents(
        task="Extract claim invoice details.",
        claim_evidence=[evidence],
    )

    assert result.extracted_fields[0].value == "2026-03-14"
    assert result.extracted_fields[0].source_evidence_ids == [str(evidence_id)]
    assert result.extracted_fields[0].page_numbers == [2]
    assert result.document_inventory[0].filename == "synthetic_claim.pdf"
    assert result.human_review_required is True
    model.with_structured_output.assert_called_once_with(
        IntakeDocumentOutput,
        method="function_calling",
    )
    structured_model.invoke.assert_called_once()

    serialized_input = json.loads(structured_model.invoke.call_args.args[0][1][1])
    supplied_record = serialized_input["claim_documents"][0]
    assert supplied_record["evidence_id"] == str(evidence_id)
    assert supplied_record["filename"] == "synthetic_claim.pdf"
    assert supplied_record["page_number"] == 2
    assert supplied_record["extraction_method"] == "native"


def test_uuid_ids_and_retrieval_dataclass_are_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dataclass UUIDs become string citation IDs without losing provenance."""
    evidence = make_retrieved_chunk()
    response = make_intake_output([str(evidence.chunk_id)])
    _, structured_model = setup_intake_model(monkeypatch, response)

    result = analyze_claim_documents(
        task="Extract claim invoice details.",
        claim_evidence=[evidence],
    )

    serialized_input = json.loads(structured_model.invoke.call_args.args[0][1][1])
    supplied_record = serialized_input["claim_documents"][0]
    assert supplied_record["evidence_id"] == str(evidence.chunk_id)
    assert supplied_record["document_id"] == str(evidence.document_id)
    assert supplied_record["filename"] == evidence.filename
    assert supplied_record["page_number"] == evidence.page_number
    assert supplied_record["extraction_method"] == "ocr"
    assert supplied_record["ocr_confidence"] == 96.5
    assert result.extracted_fields[0].source_evidence_ids == [
        str(evidence.chunk_id)
    ]


@pytest.mark.parametrize(
    "cited_ids",
    [
        ["fabricated-evidence-id"],
        [""],
    ],
)
def test_unknown_or_invalid_citations_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    cited_ids: list[str],
) -> None:
    """Citations must match retrieved evidence IDs exactly."""
    evidence = make_evidence(chunk_id=uuid4())
    response = make_intake_output(cited_ids)
    setup_intake_model(monkeypatch, response)

    with pytest.raises(IntakeAgentError, match="not retrieved"):
        analyze_claim_documents(
            task="Extract claim invoice details.",
            claim_evidence=[evidence],
        )


def test_missing_citations_are_rejected_even_for_constructed_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed structured results cannot bypass the non-empty citation check."""
    evidence = make_evidence(chunk_id=uuid4())
    field = IntakeExtractedField.model_construct(
        field_name="date_of_service",
        value="2026-03-14",
        source_evidence_ids=[],
        page_numbers=[],
        confidence="high",
        uncertain=False,
    )
    response = IntakeDocumentOutput.model_construct(
        summary="Malformed output without citations.",
        extracted_fields=[field],
        document_flags=[],
        document_inventory=[],
        missing_information=[],
        overall_assessment="documents_sufficient",
        human_review_required=True,
    )
    setup_intake_model(monkeypatch, response)

    with pytest.raises(IntakeAgentError, match="without supporting citations"):
        analyze_claim_documents(
            task="Extract claim invoice details.",
            claim_evidence=[evidence],
        )


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        {"chunk_id": None},
        {"chunk_id": uuid4(), "filename": "claim.pdf"},
        {
            "chunk_id": uuid4(),
            "filename": "claim.pdf",
            "page_number": True,
            "text": "Claim details.",
            "extraction_method": "native",
        },
        {
            "chunk_id": uuid4(),
            "filename": "claim.pdf",
            "page_number": 1,
            "text": None,
            "extraction_method": "native",
        },
        {
            "chunk_id": uuid4(),
            "filename": "claim.pdf",
            "page_number": 1,
            "text": "Claim details.",
            "extraction_method": None,
        },
    ],
)
def test_invalid_evidence_records_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    evidence: object,
) -> None:
    """Malformed retrieved records fail before the LLM is invoked."""
    get_model = MagicMock()
    monkeypatch.setattr(intake_agent, "get_chat_model", get_model)

    with pytest.raises(IntakeAgentError):
        analyze_claim_documents(
            task="Extract claim invoice details.",
            claim_evidence=[evidence],
        )

    get_model.assert_not_called()


def test_invalid_structured_payload_is_wrapped_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured output validation errors become IntakeAgentError."""
    evidence_id = uuid4()
    _, structured_model = setup_intake_model(monkeypatch, None)
    structured_model.invoke.side_effect = ValidationError.from_exception_data(
        "IntakeDocumentOutput",
        [],
    )

    with pytest.raises(IntakeAgentError, match="could not analyze"):
        analyze_claim_documents(
            task="Extract claim invoice details.",
            claim_evidence=[make_evidence(chunk_id=evidence_id)],
        )


def test_human_review_is_forced_for_constructed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The specialist forces human review even for a malformed model object."""
    evidence_id = uuid4()
    response = make_intake_output([str(evidence_id)]).model_copy(
        update={"human_review_required": False}
    )
    setup_intake_model(monkeypatch, response)

    result = analyze_claim_documents(
        task="Extract claim invoice details.",
        claim_evidence=[make_evidence(chunk_id=evidence_id)],
    )

    assert result.human_review_required is True


def test_supervisor_can_select_intake_agent_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Supervisor accepts Intake as the only available specialist."""
    plan = SupervisorPlan(
        selected_analysts=["intake_agent"],
        routing_rationale="The task requires structured document intake.",
        human_review_required=True,
    )
    structured_model = MagicMock()
    structured_model.invoke.return_value = plan
    model = MagicMock()
    model.with_structured_output.return_value = structured_model
    monkeypatch.setattr(
        "claimsage.agents.supervisor.get_chat_model",
        lambda: model,
    )

    result = create_supervisor_plan(
        task="Extract document fields and inventory.",
        claim_facts_available=True,
        policy_evidence_available=False,
        available_analysts=["intake_agent"],
    )

    assert result.selected_analysts == ["intake_agent"]
    assert result.human_review_required is True


def make_session() -> Session:
    """Create a mock database session without connecting to PostgreSQL."""
    return MagicMock(spec=Session)


def setup_graph(
    monkeypatch: pytest.MonkeyPatch,
    claim_id,
    selected_analysts: list[str],
    events: list[str],
) -> list[dict[str, object]]:
    """Mock database, retrieval, Supervisor, and specialist model operations."""
    facts = {
        "claim_id": str(claim_id),
        "claim_number": "CLM-INTAKE-001",
        "claim_type": "health",
        "policy_identifier": "TEST-HEALTH-POLICY",
        "status": "under_review",
        "summary": "Synthetic claim.",
        "created_at": None,
    }
    claim_evidence = [make_retrieved_chunk()]

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=claim_evidence),
    )
    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=selected_analysts,
                routing_rationale="Synthetic routing plan.",
                human_review_required=True,
            )
        ),
    )

    def analyze_intake(**_kwargs):
        events.append("intake")
        return make_intake_output([str(claim_evidence[0].chunk_id)])

    def analyze_evidence(**_kwargs):
        events.append("evidence")
        return MagicMock(
            model_dump=MagicMock(
                return_value={
                    "summary": "Synthetic evidence analysis.",
                    "factual_findings": [],
                    "timeline": [],
                    "inconsistencies": [],
                    "missing_information": [],
                    "evidence_gaps": [],
                    "overall_assessment": "insufficient_evidence",
                    "human_review_required": True,
                }
            )
        )

    def analyze_policy(**_kwargs):
        events.append("policy")
        return MagicMock(
            model_dump=MagicMock(
                return_value={
                    "summary": "Synthetic policy analysis.",
                    "relevant_clauses": [],
                    "coverage_indicators": [],
                    "exclusions_and_conditions": [],
                    "missing_information": [],
                    "evidence_gaps": [],
                    "overall_assessment": "insufficient_evidence",
                    "human_review_required": True,
                }
            )
        )

    monkeypatch.setattr(graph_module, "analyze_claim_documents", analyze_intake)
    monkeypatch.setattr(graph_module, "analyze_claim_evidence", analyze_evidence)
    monkeypatch.setattr(graph_module, "analyze_policy", analyze_policy)
    return claim_evidence


def test_graph_routes_intake_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Intake-only selection retrieves evidence and stops after Intake."""
    employee_id = uuid4()
    claim_id = uuid4()
    events: list[str] = []
    setup_graph(monkeypatch, claim_id, ["intake_agent"], events)

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Extract document fields and inventory.",
    )

    assert events == ["intake"]
    assert output["intake_analysis_status"] == "completed"
    assert output["intake_analysis"]["human_review_required"] is True
    assert output["evidence_analysis_status"] == "skipped"
    assert output["ai_analysis_status"] == "skipped"
    assert output["result"]["intake_analysis"] == output["intake_analysis"]
    assert output["claim_evidence_retrieval_status"] == "completed"


def test_graph_routes_intake_then_evidence_then_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined selections run Intake, Evidence Analyst, then Policy Analyst."""
    employee_id = uuid4()
    claim_id = uuid4()
    events: list[str] = []
    setup_graph(
        monkeypatch,
        claim_id,
        ["intake_agent", "evidence_analyst", "policy_analyst"],
        events,
    )

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review claim documents and policy provisions.",
    )

    assert events == ["intake", "evidence", "policy"]
    assert output["intake_analysis_status"] == "completed"
    assert output["evidence_analysis_status"] == "completed"
    assert output["ai_analysis_status"] == "completed"
    assert output["result"]["intake_analysis"] == output["intake_analysis"]
    assert output["result"]["evidence_analysis"] == output["evidence_analysis"]
    assert output["result"]["policy_analysis"] == output["policy_analysis"]
    assert output["result"]["human_review_required"] is True


def test_intake_failure_preserves_evidence_and_policy_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intake failure is isolated while subsequent specialist results complete."""
    employee_id = uuid4()
    claim_id = uuid4()
    events: list[str] = []
    setup_graph(
        monkeypatch,
        claim_id,
        ["intake_agent", "evidence_analyst", "policy_analyst"],
        events,
    )

    def fail_intake(**_kwargs):
        events.append("intake")
        raise IntakeAgentError("Synthetic Intake failure.")

    monkeypatch.setattr(graph_module, "analyze_claim_documents", fail_intake)

    output = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review claim documents and policy provisions.",
    )

    assert events == ["intake", "evidence", "policy"]
    assert output["intake_analysis"] is None
    assert output["intake_analysis_status"] == "unavailable"
    assert output["evidence_analysis_status"] == "completed"
    assert output["ai_analysis_status"] == "completed"
    assert output["result"]["evidence_analysis"] == output["evidence_analysis"]
    assert output["result"]["policy_analysis"] == output["policy_analysis"]
