"""Deterministic validation and arithmetic for repair estimate line items."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
import re
from typing import Literal

type EstimateNumber = Decimal | int | str | None
MONEY_QUANTUM = Decimal("0.01")

_CURRENCY_DECIMAL_RE = re.compile(
    r"^\s*(?:(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*)?"
    r"([+-]?(?:\d+\.?\d*|\.\d+|\d{1,3}(?:,\d{2,3})+(?:\.\d+)?(?:[eE][+-]?\d+)?))"
    r"\s*(?:(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£))?\s*$",
    re.IGNORECASE,
)

_QUANTITY_WITH_UNIT_RE = re.compile(
    r"^\s*(?:qty\.?\s*[:=-]?\s*)?([+-]?\d+(?:\.\d+)?)\s*"
    r"(?:pcs?|units?|nos?\.?|hrs?|hours?|sets?|pairs?)?\s*$",
    re.IGNORECASE,
)

_LABOR_KEYWORDS: tuple[str, ...] = (
    "labor",
    "labour",
    "painting",
    "paint",
    "fitting",
    "removal",
    "alignment",
    "blending",
    "buffing",
    "denting",
    "tinkering",
    "polishing",
    "calibration",
    "scanning",
    "overhaul",
    "r&r",
    "refitting",
    "welding",
)

_PART_KEYWORDS: tuple[str, ...] = (
    "part",
    "bumper",
    "grille",
    "clip",
    "headlamp",
    "lamp",
    "fender",
    "panel",
    "door",
    "bonnet",
    "hood",
    "windshield",
    "glass",
    "mirror",
    "radiator",
    "condenser",
    "assy",
    "assembly",
    "bracket",
    "absorber",
    "moulding",
    "retainer",
    "wheel",
    "tyre",
    "tire",
    "filter",
    "pad",
    "disc",
    "rotor",
    "sensor",
    "cover",
)


def _normalize_currency_code(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned in {"₹", "Rs", "Rs.", "rs", "rs.", "INR", "inr"}:
        return "INR"
    if cleaned in {"$", "USD", "usd"}:
        return "USD"
    if cleaned in {"€", "EUR", "eur"}:
        return "EUR"
    if cleaned in {"£", "GBP", "gbp"}:
        return "GBP"
    return cleaned.upper()


def classify_line_item_category(
    description: str | None,
) -> Literal["part", "labor", "other"]:
    """Classify a repair estimate line item as 'part', 'labor', or 'other'."""
    if not isinstance(description, str) or not description.strip():
        return "other"
    lowered = description.casefold()
    if any(kw in lowered for kw in _LABOR_KEYWORDS) and "gross part price" not in lowered:
        return "labor"
    if any(kw in lowered for kw in _PART_KEYWORDS):
        return "part"
    return "part"


@dataclass(frozen=True, slots=True)
class EstimateLineItem:
    """A source-extracted estimate item with its evidence provenance."""

    description: str | None
    quantity: EstimateNumber
    unit_amount: EstimateNumber
    source_evidence_ids: tuple[str, ...]
    reported_amount: EstimateNumber = None


@dataclass(frozen=True, slots=True)
class RepairEstimateFinding:
    """A review finding grounded in one or more source line items."""

    code: str
    description: str
    source_evidence_ids: tuple[str, ...]
    line_item_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LineItemCalculation:
    """Validation and calculated total for one supplied line item."""

    line_item_index: int
    line_total: Decimal | None
    valid: bool


@dataclass(frozen=True, slots=True)
class LineItemDetail:
    """Normalized extraction, classification, and validation detail for one line item."""

    line_item_index: int
    item_category: Literal["part", "labor", "other"]
    normalized_quantity: int | None
    normalized_unit_price: Decimal | None
    normalized_reported_amount: Decimal | None
    calculated_total: Decimal | None
    currency: str | None
    quantity_status: Literal["extracted", "unavailable", "invalid"]
    value_status: Literal[
        "calculated",
        "reported_only_quantity_unavailable",
        "calculation_error",
        "unverified",
    ]


@dataclass(frozen=True, slots=True)
class RepairEstimateCalculation:
    """Deterministic estimate calculations and completeness metadata."""

    line_calculations: tuple[LineItemCalculation, ...]
    findings: tuple[RepairEstimateFinding, ...]
    valid_line_subtotal: Decimal
    complete_estimate_total: Decimal | None
    source_data_complete: bool
    calculation_complete: bool
    completeness_status: str
    line_details: tuple[LineItemDetail, ...] = field(default_factory=tuple)
    parts_subtotal: Decimal = Decimal("0.00")
    labor_subtotal: Decimal = Decimal("0.00")
    reported_line_items_subtotal: Decimal = Decimal("0.00")
    reported_gross_total: Decimal | None = None
    reported_depreciation_total: Decimal | None = None
    reported_deductible: Decimal | None = None
    reported_net_total: Decimal | None = None
    subtotal_reconciled: bool | None = None


def normalize_currency_and_decimal(
    value: EstimateNumber,
) -> tuple[Decimal | None, str | None]:
    """Parse exact numeric inputs or currency-formatted strings into (Decimal, currency)."""

    if value is None or isinstance(value, bool) or isinstance(value, float):
        return None, None

    if isinstance(value, Decimal):
        return (value if value.is_finite() else None), None
    if isinstance(value, int):
        return Decimal(value), None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None, None
        try:
            direct = Decimal(stripped)
            if direct.is_finite():
                return direct, None
            return None, None
        except InvalidOperation:
            pass

        match = _CURRENCY_DECIMAL_RE.match(stripped)
        if match:
            curr = _normalize_currency_code(match.group(1) or match.group(3))
            num_str = match.group(2).replace(",", "")
            try:
                parsed = Decimal(num_str)
                if parsed.is_finite():
                    return parsed, curr
            except InvalidOperation:
                return None, None
    return None, None


def _parse_decimal(value: EstimateNumber) -> Decimal | None:
    """Parse supported exact numeric inputs, rejecting floats and non-finite values."""
    parsed, _ = normalize_currency_and_decimal(value)
    return parsed


def _parse_quantity(value: EstimateNumber) -> Decimal | None:
    """Parse quantity from exact numbers or explicit quantity strings (e.g. '2 pcs', 'Qty: 1')."""
    parsed = _parse_decimal(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        stripped = value.strip()
        match = _QUANTITY_WITH_UNIT_RE.match(stripped)
        if match:
            try:
                qty = Decimal(match.group(1))
                return qty if qty.is_finite() else None
            except InvalidOperation:
                return None
    return None


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except DecimalException:
        return None


def _merge_evidence_ids(
    line_items: tuple[EstimateLineItem, ...],
    indexes: tuple[int, ...],
) -> tuple[str, ...]:
    """Return unique source IDs in their original deterministic order."""

    merged: list[str] = []
    seen: set[str] = set()
    for index in indexes:
        for evidence_id in line_items[index].source_evidence_ids:
            if evidence_id not in seen:
                seen.add(evidence_id)
                merged.append(evidence_id)
    return tuple(merged)


def calculate_repair_estimate(
    line_items: list[EstimateLineItem] | tuple[EstimateLineItem, ...],
    *,
    source_data_complete: bool,
    source_evidence_ids: tuple[str, ...] = (),
    reported_totals: Mapping[str, object] | None = None,
) -> RepairEstimateCalculation:
    """Validate estimate inputs, calculate valid line totals, and flag review items.

    Monetary line totals are rounded to cents using ROUND_HALF_UP. The complete
    estimate total is available only when the caller confirms that source data
    is complete, at least one line item exists, and every supplied item is valid.
    When a line item has a unit price and/or reported amount but no quantity in
    the source document, both extracted amounts are retained and the quantity is
    flagged as unavailable without fabricating a calculation.
    """

    if not isinstance(source_data_complete, bool):
        raise ValueError("source_data_complete must be a boolean.")

    items = tuple(line_items)
    if any(not isinstance(item, EstimateLineItem) for item in items):
        raise ValueError("Every line item must be an EstimateLineItem.")

    if not isinstance(source_evidence_ids, tuple) or any(
        not isinstance(evidence_id, str) or not evidence_id.strip()
        for evidence_id in source_evidence_ids
    ):
        raise ValueError("source_evidence_ids must contain non-empty strings.")

    for item in items:
        if not isinstance(item.source_evidence_ids, tuple) or not item.source_evidence_ids:
            raise ValueError(
                "Every line item must have at least one source evidence ID."
            )
        if any(
            not isinstance(evidence_id, str) or not evidence_id.strip()
            for evidence_id in item.source_evidence_ids
        ):
            raise ValueError(
                "Line item source evidence IDs must be non-empty strings."
            )

    if not items and not source_evidence_ids:
        raise ValueError(
            "Source evidence IDs are required when no line items are provided."
        )

    findings: list[RepairEstimateFinding] = []
    calculations: list[LineItemCalculation] = []
    line_details: list[LineItemDetail] = []
    duplicate_groups: dict[tuple[str, Decimal | None, Decimal], list[int]] = {}
    subtotal = Decimal("0.00")
    parts_subtotal = Decimal("0.00")
    labor_subtotal = Decimal("0.00")
    reported_line_items_subtotal = Decimal("0.00")
    all_items_valid = True

    for index, item in enumerate(items):
        item_findings: list[str] = []

        description = item.description.strip() if isinstance(item.description, str) else ""
        category = classify_line_item_category(description)
        quantity = _parse_quantity(item.quantity)
        unit_amount, unit_curr = normalize_currency_and_decimal(item.unit_amount)
        reported_amount, rep_curr = normalize_currency_and_decimal(item.reported_amount)
        currency = unit_curr or rep_curr

        if not description:
            item_findings.append("missing_description")
            findings.append(
                RepairEstimateFinding(
                    code="missing_description",
                    description="The line item description is missing or invalid.",
                    source_evidence_ids=item.source_evidence_ids,
                    line_item_indexes=(index,),
                )
            )

        qty_status: Literal["extracted", "unavailable", "invalid"] = "extracted"
        if quantity is None:
            item_findings.append("invalid_quantity")
            is_missing_qty = item.quantity is None or (
                isinstance(item.quantity, str) and not item.quantity.strip()
            )
            qty_status = "unavailable" if is_missing_qty else "invalid"
            if is_missing_qty and (unit_amount is not None or reported_amount is not None):
                qty_msg = (
                    "The line item quantity is missing or unavailable in the source "
                    "document; unit price and reported amount were retained without "
                    "fabricating a calculation."
                )
            else:
                qty_msg = "The line item quantity is missing or invalid."
            findings.append(
                RepairEstimateFinding(
                    code="invalid_quantity",
                    description=qty_msg,
                    source_evidence_ids=item.source_evidence_ids,
                    line_item_indexes=(index,),
                )
            )
        elif quantity <= 0:
            item_findings.append("invalid_quantity")
            qty_status = "invalid"
            findings.append(
                RepairEstimateFinding(
                    code="invalid_quantity",
                    description="The line item quantity must be greater than zero.",
                    source_evidence_ids=item.source_evidence_ids,
                    line_item_indexes=(index,),
                )
            )
            quantity = None

        if unit_amount is None:
            # If reported_amount is valid and quantity is unavailable, only flag unit_amount if both are missing
            item_findings.append("invalid_unit_amount")
            findings.append(
                RepairEstimateFinding(
                    code="invalid_unit_amount",
                    description="The unit amount is missing or invalid.",
                    source_evidence_ids=item.source_evidence_ids,
                    line_item_indexes=(index,),
                )
            )
        elif unit_amount < 0:
            item_findings.append("invalid_unit_amount")
            findings.append(
                RepairEstimateFinding(
                    code="invalid_unit_amount",
                    description="The unit amount cannot be negative.",
                    source_evidence_ids=item.source_evidence_ids,
                    line_item_indexes=(index,),
                )
            )
            unit_amount = None

        norm_unit_price = _quantize_money(unit_amount) if unit_amount is not None else None
        norm_reported_amount = (
            _quantize_money(reported_amount) if reported_amount is not None else None
        )

        # Validate reported_amount if explicitly provided
        reported_amount_invalid = False
        if item.reported_amount is not None:
            if reported_amount is None:
                all_items_valid = False
                reported_amount_invalid = True
                findings.append(
                    RepairEstimateFinding(
                        code="invalid_reported_amount",
                        description=(
                            "The printed line amount is invalid and "
                            "needs clarification."
                        ),
                        source_evidence_ids=item.source_evidence_ids,
                        line_item_indexes=(index,),
                    )
                )
            elif norm_reported_amount is None:
                all_items_valid = False
                reported_amount_invalid = True
                findings.append(
                    RepairEstimateFinding(
                        code="invalid_reported_amount",
                        description=(
                            "The printed line amount cannot be "
                            "represented as a monetary value and "
                            "needs clarification."
                        ),
                        source_evidence_ids=item.source_evidence_ids,
                        line_item_indexes=(index,),
                    )
                )

        valid = not item_findings
        line_total: Decimal | None = None
        val_status: Literal[
            "calculated",
            "reported_only_quantity_unavailable",
            "calculation_error",
            "unverified",
        ] = "unverified"

        if valid and quantity is not None and unit_amount is not None:
            try:
                line_total = (quantity * unit_amount).quantize(
                    MONEY_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
            except DecimalException:
                valid = False
                all_items_valid = False
                val_status = "calculation_error"
                findings.append(
                    RepairEstimateFinding(
                        code="invalid_line_total",
                        description=(
                            "The line total cannot be represented as a valid "
                            "monetary amount."
                        ),
                        source_evidence_ids=item.source_evidence_ids,
                        line_item_indexes=(index,),
                    )
                )
            else:
                subtotal += line_total
                val_status = "calculated"
                if norm_reported_amount is not None and norm_reported_amount != line_total:
                    all_items_valid = False
                    val_status = "calculation_error"
                    findings.append(
                        RepairEstimateFinding(
                            code="reported_amount_mismatch",
                            description=(
                                "The printed line amount differs "
                                "from quantity multiplied by unit "
                                "amount; clarify whether an "
                                "adjustment or alternate basis "
                                "applies."
                            ),
                            source_evidence_ids=item.source_evidence_ids,
                            line_item_indexes=(index,),
                        )
                    )
                elif reported_amount_invalid:
                    val_status = "calculation_error"
        else:
            all_items_valid = False
            if (
                quantity is None
                and (norm_unit_price is not None or norm_reported_amount is not None)
                and not reported_amount_invalid
            ):
                val_status = "reported_only_quantity_unavailable"
            elif reported_amount_invalid:
                val_status = "calculation_error"
            else:
                val_status = "unverified"

        # Track duplicate line items both when quantity is present and when quantity is unavailable
        dedup_amount = norm_unit_price if norm_unit_price is not None else norm_reported_amount
        if description and dedup_amount is not None and (valid or quantity is None):
            duplicate_key = (description, quantity, dedup_amount)
            duplicate_groups.setdefault(duplicate_key, []).append(index)

        # Accumulate category subtotals (Gross/Unit or Calculated for parts/labor; Reported/Net for reported subtotal)
        gross_basis = (
            line_total
            if line_total is not None
            else norm_unit_price
            if norm_unit_price is not None
            else norm_reported_amount
        )
        if gross_basis is not None and gross_basis >= 0:
            if category == "labor":
                labor_subtotal += gross_basis
            else:
                parts_subtotal += gross_basis

        reported_basis = (
            norm_reported_amount
            if norm_reported_amount is not None
            else line_total
            if line_total is not None
            else norm_unit_price
        )
        if reported_basis is not None and reported_basis >= 0:
            reported_line_items_subtotal += reported_basis

        norm_qty_int: int | None = None
        if quantity is not None and quantity == quantity.to_integral_value():
            try:
                norm_qty_int = int(quantity)
            except (ValueError, OverflowError):
                norm_qty_int = None

        calculations.append(
            LineItemCalculation(
                line_item_index=index,
                line_total=line_total,
                valid=valid,
            )
        )
        line_details.append(
            LineItemDetail(
                line_item_index=index,
                item_category=category,
                normalized_quantity=norm_qty_int,
                normalized_unit_price=norm_unit_price,
                normalized_reported_amount=norm_reported_amount,
                calculated_total=line_total,
                currency=currency,
                quantity_status=qty_status,
                value_status=val_status,
            )
        )

    for indexes_list in duplicate_groups.values():
        if len(indexes_list) < 2:
            continue
        indexes = tuple(indexes_list)
        findings.append(
            RepairEstimateFinding(
                code="duplicate_line_items",
                description=(
                    "Identical line items appear more than once and need review; "
                    "this is not a fraud determination."
                ),
                source_evidence_ids=_merge_evidence_ids(items, indexes),
                line_item_indexes=indexes,
            )
        )

    # Document-level subtotal and total reconciliation when reported_totals are supplied
    rep_gross = _quantize_money(
        _parse_decimal(reported_totals.get("reported_gross_total"))  # type: ignore[arg-type]
    ) if isinstance(reported_totals, Mapping) else None
    rep_dep = _quantize_money(
        _parse_decimal(reported_totals.get("reported_depreciation_total"))  # type: ignore[arg-type]
    ) if isinstance(reported_totals, Mapping) else None
    rep_ded = _quantize_money(
        _parse_decimal(reported_totals.get("reported_deductible"))  # type: ignore[arg-type]
    ) if isinstance(reported_totals, Mapping) else None
    rep_net = _quantize_money(
        _parse_decimal(reported_totals.get("reported_net_total"))  # type: ignore[arg-type]
    ) if isinstance(reported_totals, Mapping) else None

    subtotal_reconciled: bool | None = None
    if items and (rep_gross is not None or rep_net is not None):
        all_ev_ids = _merge_evidence_ids(items, tuple(range(len(items))))
        all_idxs = tuple(range(len(items)))
        gross_sum = (parts_subtotal + labor_subtotal).quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        reconciled = True
        if rep_gross is not None and gross_sum != rep_gross:
            reconciled = False
            all_items_valid = False
            findings.append(
                RepairEstimateFinding(
                    code="subtotal_reconciliation_mismatch",
                    description=(
                        f"Sum of extracted gross line items ({gross_sum}) does not "
                        f"reconcile with printed gross estimate total ({rep_gross})."
                    ),
                    source_evidence_ids=all_ev_ids,
                    line_item_indexes=all_idxs,
                )
            )
        if rep_net is not None:
            deductible_val = rep_ded if rep_ded is not None else Decimal("0.00")
            expected_net_after_ded = (
                reported_line_items_subtotal - deductible_val
            ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            if (
                reported_line_items_subtotal != rep_net
                and expected_net_after_ded != rep_net
            ):
                reconciled = False
                all_items_valid = False
                findings.append(
                    RepairEstimateFinding(
                        code="subtotal_reconciliation_mismatch",
                        description=(
                            f"Sum of reported net line items ({reported_line_items_subtotal}) "
                            f"less deductible ({deductible_val}) equals {expected_net_after_ded}, "
                            f"which differs from printed net estimate total ({rep_net})."
                        ),
                        source_evidence_ids=all_ev_ids,
                        line_item_indexes=all_idxs,
                    )
                )
        subtotal_reconciled = reconciled

    calculation_complete = (
        source_data_complete
        and bool(items)
        and all_items_valid
    )
    if calculation_complete:
        completeness_status = "complete"
        complete_total: Decimal | None = subtotal
    elif not source_data_complete:
        completeness_status = "source_data_incomplete"
        complete_total = None
    elif not items:
        completeness_status = "no_line_items"
        complete_total = None
        findings.append(
            RepairEstimateFinding(
                code="missing_line_items",
                description="No estimate line items were supplied.",
                source_evidence_ids=source_evidence_ids,
                line_item_indexes=(),
            )
        )
    else:
        completeness_status = "invalid_line_items"
        complete_total = None

    if not source_data_complete:
        findings.append(
            RepairEstimateFinding(
                code="incomplete_source_data",
                description=(
                    "Source data is incomplete; the valid-line subtotal is partial "
                    "and no complete estimate total is reported."
                ),
                source_evidence_ids=tuple(
                    dict.fromkeys(
                        (
                            *source_evidence_ids,
                            *_merge_evidence_ids(
                                items,
                                tuple(range(len(items))),
                            ),
                        )
                    )
                ),
                line_item_indexes=tuple(range(len(items))),
            )
        )

    return RepairEstimateCalculation(
        line_calculations=tuple(calculations),
        findings=tuple(findings),
        valid_line_subtotal=subtotal.quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
        complete_estimate_total=complete_total,
        source_data_complete=source_data_complete,
        calculation_complete=calculation_complete,
        completeness_status=completeness_status,
        line_details=tuple(line_details),
        parts_subtotal=parts_subtotal.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        labor_subtotal=labor_subtotal.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        reported_line_items_subtotal=reported_line_items_subtotal.quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_UP
        ),
        reported_gross_total=rep_gross,
        reported_depreciation_total=rep_dep,
        reported_deductible=rep_ded,
        reported_net_total=rep_net,
        subtotal_reconciled=subtotal_reconciled,
    )
