"""Integration tests for the Review & Report LangGraph node."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import review_report_agent as review_report_module
from claimsage.agents.graph import run_investigation
from claimsage.agents.review_report_agent import ReviewReportAgentError
from claimsage.agents.risk_anomaly_agent import RiskAnomalyAgentError
from claimsage.agents.schemas import (
    EvidenceAnalystOutput,
    IntakeDocumentInventoryItem,
    IntakeDocumentOutput,
    PolicyAnalystOutput,
    RepairEstimateAnalystOutput,
    ReviewReportExtraction,
    ReviewReportOutput,
    ReviewReportSpecialistCoverage,
    RiskAnomalyOutput,
    SupervisorPlan,
)
from claimsage.rag.evidence_retrieval_service import EvidenceRetrievalError
from claimsage.services.claim_access import ClaimAccessDeniedError


def make_session() -> Session:
    return MagicMock(spec=Session)


def make_chunk(filename: str):
    chunk = MagicMock()
    chunk.chunk_id = uuid4()
    chunk.document_id = uuid4()
    chunk.filename = filename
    chunk.page_number = 2
    chunk.chunk_index = 1
    chunk.text = f"Canonical text for {filename}."
    chunk.similarity = 0.87
    chunk.embedding_model = "test-embedding-model"
    chunk.extraction_method = "native"
    chunk.ocr_confidence = None
    chunk.clause_id = None
    chunk.clause_identifier = None
    chunk.clause_category = None
    chunk.verification_status = None
    chunk.policy_version = None
    chunk.source_url = None
    chunk.insurer_name = None
    chunk.product_name = None
    chunk.policy_identifier = None
    chunk.effective_from = None
    chunk.effective_to = None
    return chunk


def make_report() -> ReviewReportOutput:
    return ReviewReportOutput(
        overall_status="insufficient_evidence",
        specialist_coverage=[
            ReviewReportSpecialistCoverage(
                specialist="intake_agent",
                status="completed",
                analysis_included=True,
            )
        ],
        evidence_retrieval_status="completed",
        evidence_scope_note=(
            "This report covers only the evidence retrieved for this "
            "investigation."
        ),
        human_review_required=True,
    )


def setup_graph(
    monkeypatch: pytest.MonkeyPatch,
    selected_analysts: list[str],
    *,
    claim_chunks: list[object] | None = None,
    policy_chunks: list[object] | None = None,
    claim_retrieval_error: bool = False,
):
    claim_id = uuid4()
    employee_id = uuid4()
    facts = {
        "claim_id": str(claim_id),
        "claim_number": "CLM-REPORT-001",
        "claim_type": "property",
        "policy_identifier": "TEST-PROPERTY-POLICY",
        "status": "under_review",
    }
    claim_retrieval = MagicMock(
        side_effect=(
            EvidenceRetrievalError("Synthetic retrieval failure.")
            if claim_retrieval_error
            else None
        ),
        return_value=claim_chunks or [],
    )
    if claim_retrieval_error:
        claim_retrieval = MagicMock(
            side_effect=EvidenceRetrievalError("Synthetic retrieval failure.")
        )

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(return_value=facts),
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        MagicMock(return_value=policy_chunks or []),
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        claim_retrieval,
    )
    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=selected_analysts,
                routing_rationale="Synthetic integration test routing.",
                human_review_required=True,
            )
        ),
    )

    monkeypatch.setattr(
        graph_module,
        "analyze_claim_documents",
        MagicMock(
            return_value=IntakeDocumentOutput(
                summary="Document fields retained for human review.",
                document_inventory=[
                    IntakeDocumentInventoryItem(
                        filename="model-supplied-name.pdf",
                        document_type="claim document",
                        status="uncertain",
                        source_evidence_ids=(
                            [str(claim_chunks[0].chunk_id)]
                            if claim_chunks
                            else ["synthetic-reference"]
                        ),
                    )
                ]
                if claim_chunks
                else [],
                overall_assessment="documents_incomplete",
                human_review_required=True,
            )
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_claim_evidence",
        MagicMock(
            return_value=EvidenceAnalystOutput(
                summary="Evidence review completed.",
                overall_assessment="insufficient_evidence",
                human_review_required=True,
            )
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_policy",
        MagicMock(
            return_value=PolicyAnalystOutput(
                summary="Policy review completed.",
                overall_assessment="insufficient_evidence",
                human_review_required=True,
            )
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_repair_estimate",
        MagicMock(
            return_value=RepairEstimateAnalystOutput(
                estimate_status="incomplete",
                source_data_complete=False,
                calculation_complete=False,
                human_review_required=True,
            )
        ),
    )

    return employee_id, claim_id, facts, claim_retrieval


def test_report_runs_after_intake_and_multiple_specialist_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for selected in (
        ["intake_agent"],
        ["intake_agent", "evidence_analyst", "policy_analyst"],
    ):
        chunk = make_chunk("canonical_claim_document.pdf")
        _, _, _, _ = setup_graph(
            monkeypatch,
            selected,
            claim_chunks=[chunk],
            policy_chunks=[make_chunk("canonical_policy.pdf")],
        )
        execution_order: list[str] = []
        report_inputs = []
        intake_analyzer = graph_module.analyze_claim_documents

        def create_report(*, report_input):
            execution_order.append("report")
            report_inputs.append(report_input)
            return make_report()

        report = MagicMock(side_effect=create_report)
        monkeypatch.setattr(
            graph_module,
            "analyze_claim_documents",
            MagicMock(
                side_effect=lambda **kwargs: (
                    execution_order.append("intake"),
                    intake_analyzer(**kwargs),
                )[1]
            ),
        )
        evidence_analyzer = graph_module.analyze_claim_evidence
        monkeypatch.setattr(
            graph_module,
            "analyze_claim_evidence",
            MagicMock(
                side_effect=lambda **kwargs: (
                    execution_order.append("evidence"),
                    evidence_analyzer(**kwargs),
                )[1]
            ),
        )
        policy_analyzer = graph_module.analyze_policy
        monkeypatch.setattr(
            graph_module,
            "analyze_policy",
            MagicMock(
                side_effect=lambda **kwargs: (
                    execution_order.append("policy"),
                    policy_analyzer(**kwargs),
                )[1]
            ),
        )
        monkeypatch.setattr(graph_module, "analyze_review_report", report)

        outcome = run_investigation(
            session=make_session(),
            employee_id=uuid4(),
            claim_id=uuid4(),
            task="Review the retrieved claim documents.",
        )

        assert outcome["review_report_status"] == "completed"
        assert outcome["review_report"] == make_report()
        assert outcome["result"]["review_report"] == make_report().model_dump(
            mode="json"
        )
        assert outcome["result"]["human_review_required"] is True
        assert execution_order[-1] == "report"
        if selected == ["intake_agent"]:
            assert execution_order == ["intake", "report"]
        else:
            assert execution_order == ["intake", "evidence", "policy", "report"]
            assert (
                report_inputs[0].evidence_analyst.status
                == "insufficient_evidence"
            )
            assert (
                report_inputs[0].policy_analyst.status
                == "insufficient_evidence"
            )
        report.assert_called_once()


def test_report_generates_when_policy_and_estimate_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id, claim_id, _, _ = setup_graph(
        monkeypatch,
        ["intake_agent", "evidence_analyst"],
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=False),
    )
    structured_model = MagicMock()
    structured_model.invoke.return_value = ReviewReportExtraction()
    chat_model = MagicMock()
    chat_model.with_structured_output.return_value = structured_model
    monkeypatch.setattr(
        review_report_module,
        "get_chat_model",
        MagicMock(return_value=chat_model),
    )

    outcome = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the available claim evidence for human review.",
    )

    assert outcome["policy_retrieval_status"] == "no_applicable_policy"
    assert outcome["ai_analysis_status"] == "skipped"
    assert outcome["policy_analysis"] is None
    assert outcome["repair_estimate_analysis_status"] == "skipped"
    assert outcome["repair_estimate_analysis"] is None
    assert outcome["risk_analysis_status"] == "skipped"
    assert outcome["review_report_status"] == "completed"
    assert outcome["review_report"] is not None
    assert outcome["review_report"].human_review_required is True
    assert outcome["result"]["human_review_required"] is True
    coverage = {
        item.specialist: item
        for item in outcome["review_report"].specialist_coverage
    }
    assert coverage["policy_analyst"].status == "skipped"
    assert coverage["repair_estimate_analyst"].status == "skipped"
    assert coverage["risk_anomaly_agent"].status == "skipped"
    structured_model.invoke.assert_called_once()


def test_report_succeeds_with_qualified_unavailable_risk_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id, claim_id, _, _ = setup_graph(
        monkeypatch,
        ["intake_agent", "evidence_analyst", "risk_anomaly_agent"],
        claim_chunks=[make_chunk("synthetic_claim_evidence.pdf")],
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        MagicMock(return_value=False),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_risk_and_anomalies",
        MagicMock(
            side_effect=RiskAnomalyAgentError("Synthetic provider failure.")
        ),
    )
    structured_model = MagicMock()
    structured_model.invoke.return_value = ReviewReportExtraction()
    chat_model = MagicMock()
    chat_model.with_structured_output.return_value = structured_model
    monkeypatch.setattr(
        review_report_module,
        "get_chat_model",
        MagicMock(return_value=chat_model),
    )

    outcome = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review available evidence and summarize limitations.",
    )

    assert outcome["risk_analysis"] is None
    assert outcome["risk_analysis_status"] == "unavailable"
    assert outcome["review_report_status"] == "incomplete"
    report = outcome["review_report"]
    assert report is not None
    assert report.overall_status == "incomplete"
    assert report.human_review_required is True
    assert report.observed_facts == []
    assert report.analyst_interpretations == []
    coverage = {item.specialist: item for item in report.specialist_coverage}
    assert coverage["risk_anomaly_agent"].status == "unavailable"
    assert coverage["risk_anomaly_agent"].analysis_included is False
    assert coverage["policy_analyst"].status == "skipped"
    assert coverage["repair_estimate_analyst"].status == "skipped"
    assert outcome["result"]["risk_analysis_status"] == "unavailable"
    assert outcome["result"]["human_review_required"] is True
    structured_model.invoke.assert_called_once()


@pytest.mark.parametrize(
    ("specialist", "event_name", "has_claim_evidence"),
    [
        ("evidence_analyst", "evidence", False),
        ("policy_analyst", "policy", False),
        ("repair_estimate_analyst", "repair_estimate", False),
        ("risk_anomaly_agent", "risk_anomaly", True),
    ],
)
def test_report_runs_once_after_each_remaining_terminal_route(
    monkeypatch: pytest.MonkeyPatch,
    specialist: str,
    event_name: str,
    has_claim_evidence: bool,
) -> None:
    claim_chunk = make_chunk("risk_claim.pdf") if has_claim_evidence else None
    employee_id, claim_id, _, _ = setup_graph(
        monkeypatch,
        [specialist],
        claim_chunks=[claim_chunk] if claim_chunk is not None else [],
    )
    events: list[str] = []

    def record_call(name, function):
        def recorded(**kwargs):
            events.append(name)
            return function(**kwargs)

        return recorded

    if specialist == "repair_estimate_analyst":
        estimate_chunk = make_chunk("repair_estimate.pdf")
        document_id = estimate_chunk.document_id
        monkeypatch.setattr(
            graph_module,
            "get_document_evidence_chunks",
            MagicMock(return_value=[estimate_chunk]),
        )
        estimate_output = RepairEstimateAnalystOutput(
            estimate_status="complete",
            source_data_complete=True,
            calculation_complete=False,
            human_review_required=True,
        )
        monkeypatch.setattr(
            graph_module,
            "analyze_repair_estimate",
            record_call(
                event_name,
                MagicMock(return_value=estimate_output),
            ),
        )
    else:
        document_id = None

    if specialist == "risk_anomaly_agent":
        monkeypatch.setattr(
            graph_module,
            "analyze_risk_and_anomalies",
            record_call(
                event_name,
                MagicMock(
                    return_value=RiskAnomalyOutput(
                        overall_status="analyzed",
                        human_review_required=True,
                    )
                ),
            ),
        )
    elif specialist == "evidence_analyst":
        monkeypatch.setattr(
            graph_module,
            "analyze_claim_evidence",
            record_call(
                event_name,
                graph_module.analyze_claim_evidence,
            ),
        )
    elif specialist == "policy_analyst":
        monkeypatch.setattr(
            graph_module,
            "analyze_policy",
            record_call(event_name, graph_module.analyze_policy),
        )

    def create_report(*, report_input):
        events.append("report")
        return make_report()

    report = MagicMock(side_effect=create_report)
    monkeypatch.setattr(graph_module, "analyze_review_report", report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=employee_id,
        claim_id=claim_id,
        task="Review the selected specialist findings.",
        repair_estimate_document_id=document_id,
    )

    assert events == [event_name, "report"]
    report.assert_called_once()
    assert outcome["review_report_status"] == "completed"
    assert outcome["result"]["human_review_required"] is True
    assert outcome["selected_analysts"] == [specialist]


def test_report_input_preserves_canonical_evidence_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_chunk = make_chunk("trusted_claim.pdf")
    policy_chunk = make_chunk("trusted_policy.pdf")
    setup_graph(
        monkeypatch,
        ["intake_agent"],
        claim_chunks=[claim_chunk],
        policy_chunks=[policy_chunk],
    )
    captured = {}

    def create_report(*, report_input):
        captured["input"] = report_input
        return make_report()

    monkeypatch.setattr(graph_module, "analyze_review_report", create_report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review document provenance.",
    )

    evidence = captured["input"].retrieved_evidence
    assert [item.chunk_id for item in evidence] == [
        str(claim_chunk.chunk_id),
        str(policy_chunk.chunk_id),
    ]
    assert evidence[0].document_id == str(claim_chunk.document_id)
    assert evidence[0].filename == "trusted_claim.pdf"
    assert evidence[0].page_number == claim_chunk.page_number
    assert evidence[0].text == claim_chunk.text
    assert evidence[0].extraction_method == "native"
    assert evidence[1].filename == "trusted_policy.pdf"
    assert (
        captured["input"].intake_agent.analysis["document_inventory"][0][
            "filename"
        ]
        == "model-supplied-name.pdf"
    )
    assert outcome["result"]["review_report_status"] == "completed"


def test_report_failure_preserves_specialist_results_and_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, _, _, _ = setup_graph(monkeypatch, ["intake_agent"])
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            side_effect=ReviewReportAgentError("Synthetic report failure.")
        ),
    )

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review the claim.",
    )

    assert outcome["error"] is None
    assert outcome["review_report"] is None
    assert outcome["review_report_status"] == "unavailable"
    assert outcome["intake_analysis_status"] == "completed"
    assert outcome["intake_analysis"] is not None
    assert outcome["result"]["intake_analysis"] == outcome["intake_analysis"]
    assert outcome["result"]["human_review_required"] is True
    assert any(
        "Review & Report generation is temporarily unavailable" in item
        for item in outcome["result"]["limitations"]
    )
    assert "Review report generation failed at agent_execution" in caplog.text
    assert "error_type=ReviewReportAgentError" in caplog.text
    assert "Synthetic report failure." not in caplog.text


def test_incomplete_report_is_not_marked_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "claim_facts": {"claim_id": "claim-id"},
        "claim_evidence": [],
        "claim_evidence_retrieval_status": "completed",
        "policy_evidence": [],
        "policy_retrieval_status": "no_relevant_evidence",
        "repair_estimate_evidence": [],
        "repair_estimate_document_id": None,
        "selected_analysts": [],
        "intake_analysis": None,
        "intake_analysis_status": "skipped",
        "evidence_analysis": None,
        "evidence_analysis_status": "skipped",
        "policy_analysis": None,
        "ai_analysis_status": "skipped",
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "skipped",
        "risk_analysis": None,
        "risk_analysis_status": "skipped",
        "result": {"limitations": []},
    }
    incomplete_report = make_report().model_copy(
        update={"overall_status": "incomplete"}
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(return_value=incomplete_report),
    )

    update = graph_module.run_review_report(state)

    assert update["review_report"] == incomplete_report
    assert update["review_report_status"] == "incomplete"
    assert update["result"]["review_report_status"] == "incomplete"
    assert update["result"]["human_review_required"] is True


def test_unexpected_report_exception_preserves_all_existing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake_analysis = {
        "summary": "Completed intake output.",
        "overall_assessment": "documents_incomplete",
        "human_review_required": True,
    }
    evidence_analysis = {
        "summary": "Completed evidence output.",
        "overall_assessment": "supportive",
        "human_review_required": True,
    }
    prior_result = {
        "intake_analysis": intake_analysis,
        "intake_analysis_status": "completed",
        "evidence_analysis": evidence_analysis,
        "evidence_analysis_status": "completed",
        "limitations": ["An earlier limitation."],
    }
    state = {
        "claim_facts": {"claim_id": "authorized-claim"},
        "claim_evidence": [],
        "claim_evidence_retrieval_status": "completed",
        "policy_evidence": [],
        "policy_retrieval_status": "no_relevant_evidence",
        "repair_estimate_evidence": [],
        "repair_estimate_document_id": None,
        "selected_analysts": ["intake_agent", "evidence_analyst"],
        "intake_analysis": intake_analysis,
        "intake_analysis_status": "completed",
        "evidence_analysis": evidence_analysis,
        "evidence_analysis_status": "completed",
        "policy_analysis": None,
        "ai_analysis_status": "skipped",
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "skipped",
        "risk_analysis": None,
        "risk_analysis_status": "skipped",
        "result": prior_result,
        "error": "A pre-existing investigation warning.",
    }
    report = MagicMock(side_effect=RuntimeError("Synthetic unexpected failure."))
    monkeypatch.setattr(graph_module, "analyze_review_report", report)

    update = graph_module.run_review_report(state)
    merged_state = {**state, **update}

    assert merged_state["intake_analysis"] == intake_analysis
    assert merged_state["intake_analysis_status"] == "completed"
    assert merged_state["evidence_analysis"] == evidence_analysis
    assert merged_state["evidence_analysis_status"] == "completed"
    assert merged_state["error"] == "A pre-existing investigation warning."
    assert merged_state["review_report"] is None
    assert merged_state["review_report_status"] == "unavailable"
    assert merged_state["result"]["intake_analysis"] == intake_analysis
    assert merged_state["result"]["evidence_analysis"] == evidence_analysis
    assert merged_state["result"]["limitations"] == [
        "An earlier limitation.",
        (
            "Review & Report generation is temporarily unavailable. "
            "Specialist results were retained for mandatory human review."
        ),
    ]
    report.assert_called_once()


def test_mixed_retrieval_outcomes_are_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_chunk = make_chunk("available_policy.pdf")
    setup_graph(
        monkeypatch,
        ["intake_agent"],
        policy_chunks=[policy_chunk],
        claim_retrieval_error=True,
    )
    captured = {}

    def create_report(*, report_input):
        captured["input"] = report_input
        return make_report()

    monkeypatch.setattr(graph_module, "analyze_review_report", create_report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review retrieved evidence.",
    )

    report_input = captured["input"]
    assert report_input.evidence_retrieval_status == "limited"
    assert len(report_input.retrieved_evidence) == 1
    assert any(
        "Claim evidence retrieval or analysis was unavailable" in item
        for item in report_input.evidence_retrieval_limitations
    )
    assert outcome["review_report_status"] == "completed"


def test_report_input_preserves_specialist_execution_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "claim_facts": {"claim_id": "claim-id"},
        "claim_evidence": [],
        "claim_evidence_retrieval_status": "completed",
        "policy_evidence": [],
        "policy_retrieval_status": "no_relevant_evidence",
        "repair_estimate_evidence": [],
        "repair_estimate_document_id": "document-id",
        "selected_analysts": ["repair_estimate_analyst"],
        "intake_analysis": None,
        "intake_analysis_status": "skipped",
        "evidence_analysis": None,
        "evidence_analysis_status": "unavailable",
        "policy_analysis": None,
        "ai_analysis_status": "failed",
        "repair_estimate_analysis": {
            "estimate_status": "incomplete",
            "source_data_complete": False,
            "calculation_complete": False,
            "human_review_required": True,
        },
        "repair_estimate_analysis_status": "insufficient_evidence",
        "risk_analysis": None,
        "risk_analysis_status": "skipped",
        "result": {"limitations": []},
    }
    captured = {}

    def create_report(*, report_input):
        captured["input"] = report_input
        return make_report()

    monkeypatch.setattr(graph_module, "analyze_review_report", create_report)
    result = graph_module.run_review_report(state)

    report_input = captured["input"]
    assert report_input.intake_agent.status == "skipped"
    assert report_input.intake_agent.analysis is None
    assert report_input.evidence_analyst.status == "unavailable"
    assert report_input.evidence_analyst.analysis is None
    assert report_input.policy_analyst.status == "failed"
    assert report_input.policy_analyst.analysis is None
    assert report_input.repair_estimate_analyst.status == (
        "insufficient_evidence"
    )
    assert report_input.repair_estimate_analyst.analysis is not None
    assert result["review_report_status"] == "completed"
    assert result["review_report"].human_review_required is True


def test_conflicting_duplicate_evidence_rejects_report_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_chunk("same.pdf")
    second = make_chunk("same.pdf")
    second.chunk_id = first.chunk_id
    second.text = "Conflicting text under the same evidence ID."
    setup_graph(
        monkeypatch,
        ["intake_agent"],
        claim_chunks=[first],
        policy_chunks=[second],
    )
    report = MagicMock(return_value=make_report())
    monkeypatch.setattr(graph_module, "analyze_review_report", report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review evidence.",
    )

    assert outcome["review_report_status"] == "unavailable"
    assert outcome["review_report"] is None
    assert outcome["intake_analysis_status"] == "completed"
    assert any(
        "Review & Report generation is temporarily unavailable" in item
        for item in outcome["result"]["limitations"]
    )
    report.assert_not_called()


def test_identical_duplicate_evidence_is_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = make_chunk("same.pdf")
    setup_graph(
        monkeypatch,
        ["intake_agent"],
        claim_chunks=[chunk],
        policy_chunks=[chunk],
    )
    captured = {}

    def create_report(*, report_input):
        captured["input"] = report_input
        return make_report()

    monkeypatch.setattr(graph_module, "analyze_review_report", create_report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review duplicate evidence.",
    )

    assert len(captured["input"].retrieved_evidence) == 1
    assert captured["input"].retrieved_evidence[0].chunk_id == str(
        chunk.chunk_id
    )
    assert outcome["review_report_status"] == "completed"


def test_authorization_failure_skips_report_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        MagicMock(
            side_effect=ClaimAccessDeniedError(
                "Claim not found or access denied."
            )
        ),
    )
    report = MagicMock(return_value=make_report())
    monkeypatch.setattr(graph_module, "analyze_review_report", report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Review the claim.",
    )

    assert outcome["result"] is None
    assert outcome["review_report"] is None
    assert outcome["review_report_status"] == "skipped"
    report.assert_not_called()


def test_setup_failure_skips_report_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = MagicMock(return_value=make_report())
    monkeypatch.setattr(graph_module, "analyze_review_report", report)

    outcome = run_investigation(
        session=make_session(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="   ",
    )

    assert outcome["error"] == "An investigation task is required."
    assert outcome["result"] is None
    assert outcome["review_report"] is None
    assert outcome["review_report_status"] == "skipped"
    report.assert_not_called()
