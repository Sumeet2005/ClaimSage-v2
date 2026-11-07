"""Unit tests for deterministic repair estimate calculations."""

from decimal import Decimal

import pytest

from claimsage.agents.repair_estimate_rules import (
    EstimateLineItem,
    calculate_repair_estimate,
)


def line_item(
    description: str | None = "Replace front panel",
    quantity: Decimal | int | str | float | None = Decimal("1"),
    unit_amount: Decimal | int | str | float | None = Decimal("125.00"),
    evidence_ids: tuple[str, ...] = ("evidence-1",),
    reported_amount: Decimal | int | str | float | None = None,
) -> EstimateLineItem:
    """Create one synthetic estimate line item."""
    return EstimateLineItem(
        description=description,
        quantity=quantity,  # type: ignore[arg-type]
        unit_amount=unit_amount,  # type: ignore[arg-type]
        source_evidence_ids=evidence_ids,
        reported_amount=reported_amount,  # type: ignore[arg-type]
    )


def test_calculates_exact_decimal_line_totals_and_estimate_total() -> None:
    """Valid values are multiplied and rounded to cents using half-up rounding."""
    result = calculate_repair_estimate(
        [
            line_item(
                description="Paint materials",
                quantity="1",
                unit_amount="0.005",
            ),
            line_item(
                description="Panel labor",
                quantity=Decimal("2.5"),
                unit_amount=Decimal("10.10"),
                evidence_ids=("evidence-2",),
            ),
        ],
        source_data_complete=True,
    )

    assert [item.line_total for item in result.line_calculations] == [
        Decimal("0.01"),
        Decimal("25.25"),
    ]
    assert result.valid_line_subtotal == Decimal("25.26")
    assert result.complete_estimate_total == Decimal("25.26")
    assert result.calculation_complete is True
    assert result.completeness_status == "complete"


@pytest.mark.parametrize(
    ("quantity", "unit_amount", "expected_code"),
    [
        ("not-a-number", "10.00", "invalid_quantity"),
        ("NaN", "10.00", "invalid_quantity"),
        (0, "10.00", "invalid_quantity"),
        (-1, "10.00", "invalid_quantity"),
        ("1", "invalid-amount", "invalid_unit_amount"),
        ("1", "-0.01", "invalid_unit_amount"),
        ("1", float("inf"), "invalid_unit_amount"),
        ("1", 1.25, "invalid_unit_amount"),
    ],
)
def test_invalid_quantity_or_unit_amount_is_not_calculated(
    quantity,
    unit_amount,
    expected_code: str,
) -> None:
    """Invalid or inexact numeric inputs produce findings and no line total."""
    result = calculate_repair_estimate(
        [line_item(quantity=quantity, unit_amount=unit_amount)],
        source_data_complete=True,
    )

    assert result.line_calculations[0].valid is False
    assert result.line_calculations[0].line_total is None
    assert result.complete_estimate_total is None
    assert result.calculation_complete is False
    assert expected_code in {finding.code for finding in result.findings}
    assert result.findings[0].source_evidence_ids == ("evidence-1",)


def test_missing_description_and_values_are_identified() -> None:
    """Missing description, quantity, and unit amount are separately reported."""
    result = calculate_repair_estimate(
        [
            line_item(
                description=" ",
                quantity=None,
                unit_amount=None,
            )
        ],
        source_data_complete=True,
    )

    assert {
        finding.code
        for finding in result.findings
    } == {
        "missing_description",
        "invalid_quantity",
        "invalid_unit_amount",
    }
    assert all(
        finding.source_evidence_ids == ("evidence-1",)
        for finding in result.findings
    )
    assert result.valid_line_subtotal == Decimal("0.00")
    assert result.complete_estimate_total is None
    assert result.completeness_status == "invalid_line_items"


def test_exact_duplicate_items_are_flagged_for_review_with_both_sources() -> None:
    """Duplicates create a review finding, not a fraud conclusion."""
    result = calculate_repair_estimate(
        [
            line_item(evidence_ids=("estimate-page-1",)),
            line_item(evidence_ids=("estimate-page-2",)),
        ],
        source_data_complete=True,
    )

    duplicate_findings = [
        finding
        for finding in result.findings
        if finding.code == "duplicate_line_items"
    ]
    assert len(duplicate_findings) == 1
    assert duplicate_findings[0].source_evidence_ids == (
        "estimate-page-1",
        "estimate-page-2",
    )
    assert duplicate_findings[0].line_item_indexes == (0, 1)
    assert "fraud" in duplicate_findings[0].description
    assert result.complete_estimate_total == Decimal("250.00")


def test_reported_amount_mismatch_requires_review_and_blocks_complete_total() -> None:
    """A printed amount conflict is cited and cannot appear complete."""
    result = calculate_repair_estimate(
        [
            line_item(
                quantity="2",
                unit_amount="125.25",
                reported_amount="999999.99",
            )
        ],
        source_data_complete=True,
    )

    finding = next(
        finding
        for finding in result.findings
        if finding.code == "reported_amount_mismatch"
    )
    assert finding.source_evidence_ids == ("evidence-1",)
    assert finding.line_item_indexes == (0,)
    assert result.valid_line_subtotal == Decimal("250.50")
    assert result.complete_estimate_total is None
    assert result.calculation_complete is False
    assert result.completeness_status == "invalid_line_items"


def test_matching_reported_amount_allows_complete_calculation() -> None:
    """A matching printed amount is checked without overriding calculation."""
    result = calculate_repair_estimate(
        [
            line_item(
                quantity="2",
                unit_amount="125.25",
                reported_amount="250.50",
            )
        ],
        source_data_complete=True,
    )

    assert not result.findings
    assert result.complete_estimate_total == Decimal("250.50")
    assert result.calculation_complete is True


def test_invalid_reported_amount_requires_review_and_blocks_complete_total() -> None:
    """A non-numeric printed amount cannot be silently ignored."""
    result = calculate_repair_estimate(
        [line_item(reported_amount="not an amount")],
        source_data_complete=True,
    )

    finding = next(
        finding
        for finding in result.findings
        if finding.code == "invalid_reported_amount"
    )
    assert finding.source_evidence_ids == ("evidence-1",)
    assert result.complete_estimate_total is None
    assert result.calculation_complete is False


def test_incomplete_source_never_reports_a_complete_estimate_total() -> None:
    """A valid-line subtotal remains explicitly partial if source data is incomplete."""
    result = calculate_repair_estimate(
        [
            line_item(
                quantity=2,
                unit_amount="40.00",
                evidence_ids=("estimate-page-1",),
            )
        ],
        source_data_complete=False,
        source_evidence_ids=("estimate-document",),
    )

    assert result.valid_line_subtotal == Decimal("80.00")
    assert result.complete_estimate_total is None
    assert result.calculation_complete is False
    assert result.completeness_status == "source_data_incomplete"
    incomplete_finding = next(
        finding
        for finding in result.findings
        if finding.code == "incomplete_source_data"
    )
    assert incomplete_finding.source_evidence_ids == (
        "estimate-document",
        "estimate-page-1",
    )
    assert "partial" in incomplete_finding.description


def test_empty_estimate_requires_document_citation_and_is_incomplete() -> None:
    """An empty extracted item list is not mistaken for a zero-value complete estimate."""
    result = calculate_repair_estimate(
        [],
        source_data_complete=True,
        source_evidence_ids=("estimate-document",),
    )

    assert result.complete_estimate_total is None
    assert result.calculation_complete is False
    assert result.completeness_status == "no_line_items"
    assert result.findings[0].code == "missing_line_items"
    assert result.findings[0].source_evidence_ids == ("estimate-document",)


def test_findings_preserve_source_evidence_ids() -> None:
    """Validation findings retain the exact cited source IDs from the input."""
    source_ids = ("estimate-page-3", "estimate-page-4")
    result = calculate_repair_estimate(
        [
            line_item(
                quantity=None,
                evidence_ids=source_ids,
            )
        ],
        source_data_complete=True,
    )

    assert result.findings[0].source_evidence_ids == source_ids


def test_missing_line_item_citations_are_rejected() -> None:
    """The service does not emit uncited line-item findings."""
    with pytest.raises(ValueError, match="source evidence ID"):
        calculate_repair_estimate(
            [line_item(evidence_ids=())],
            source_data_complete=True,
        )


def test_document_level_findings_require_citations_for_empty_items() -> None:
    """An empty estimate cannot create a missing-items finding without evidence."""
    with pytest.raises(ValueError, match="Source evidence IDs are required"):
        calculate_repair_estimate(
            [],
            source_data_complete=True,
        )


def test_source_completeness_must_be_boolean() -> None:
    """Completeness cannot be inferred from a truthy non-boolean value."""
    with pytest.raises(ValueError, match="must be a boolean"):
        calculate_repair_estimate(  # type: ignore[arg-type]
            [line_item()],
            source_data_complete=1,
        )


def test_decimal_overflow_is_reported_instead_of_returning_invalid_total() -> None:
    """Values that cannot be quantized safely are rejected as line totals."""
    result = calculate_repair_estimate(
        [
            line_item(
                quantity="1E+1000000",
                unit_amount="1",
            )
        ],
        source_data_complete=True,
    )

    assert result.line_calculations[0].valid is False
    assert result.line_calculations[0].line_total is None
    assert "invalid_line_total" in {
        finding.code for finding in result.findings
    }
    assert result.complete_estimate_total is None
