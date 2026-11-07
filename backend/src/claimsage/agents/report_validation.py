"""Global investigation report quality, source attribution, reconciliation, and validation.

Provides reusable, claimant-agnostic, and claim-type-aware validation across all
ClaimSage investigations, specialists, and insurance domains (health, motor/auto,
property, and general claims).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Literal

from claimsage.agents.llm import quote_matches_evidence
from claimsage.agents.schemas import (
    DocumentEvidenceStatus,
    MissingInformationCategory,
    MissingInformationReconciliationItem,
    ReportSourceInventoryItem,
    ReviewReportAnalystOutputReference,
    ReviewReportConflictAssertion,
    ReviewReportEvidenceChunk,
    ReviewReportEvidenceQuote,
    ReviewReportInput,
    ReviewReportItem,
    ReviewReportOutput,
    ReviewReportSourceReference,
    ReviewReportSpecialistName,
)

CANONICAL_SPECIALISTS: tuple[ReviewReportSpecialistName, ...] = (
    "intake_agent",
    "evidence_analyst",
    "policy_analyst",
    "repair_estimate_analyst",
    "risk_anomaly_agent",
)

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "were",
        "was",
        "are",
        "has",
        "have",
        "had",
        "not",
        "but",
        "its",
        "into",
        "only",
        "also",
        "than",
        "then",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "can",
        "cannot",
        "under",
        "over",
        "between",
        "across",
        "within",
        "without",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "about",
        "there",
        "their",
        "they",
        "them",
        "these",
        "those",
        "such",
        "some",
        "any",
        "each",
        "every",
        "other",
        "another",
        "more",
        "most",
        "less",
        "least",
        "very",
        "just",
        "been",
        "being",
        "does",
        "did",
        "done",
        "doing",
        "claim",
        "document",
        "documents",
        "evidence",
        "report",
        "reported",
        "stated",
        "states",
        "shows",
        "shown",
        "indicates",
        "indicated",
        "found",
        "finding",
        "findings",
        "record",
        "records",
        "review",
        "human",
        "analyst",
        "specialist",
        "source",
        "sources",
        "available",
        "provided",
        "retrieved",
        "information",
    }
)

_MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# Domain applicability keywords
_MOTOR_ONLY_KEYWORDS: tuple[str, ...] = (
    "repair estimate",
    "vehicle registration",
    "registration certificate",
    "rc book",
    "driving licence",
    "driving license",
    "driver licence",
    "driver license",
    "insured declared value",
    "idv",
    "chassis number",
    "engine number",
    "odometer",
    "bumper",
    "windshield",
    "fender",
    "headlamp",
    "motor survey",
    "garage estimate",
    "workshop estimate",
)

_HEALTH_ONLY_KEYWORDS: tuple[str, ...] = (
    "discharge summary",
    "hospitalization",
    "inpatient",
    "room rent",
    "nursing charges",
    "icu charges",
    "histopathology",
    "biopsy",
    "icd-10",
    "icd code",
    "pre-authorization for surgery",
    "attending physician",
    "operation theatre",
    "surgical notes",
)


@dataclass(frozen=True)
class IndexedSpecialistFinding:
    """Canonical record of a single finding produced by a completed specialist."""

    specialist: ReviewReportSpecialistName
    output_path: str
    finding_text: str
    explanation_text: str = ""
    evidence_ids: tuple[str, ...] = ()
    category: str = "general"


@dataclass
class ExtractedStructuredValue:
    """A date, financial amount, or entity extracted with full provenance."""

    kind: Literal["date", "amount", "entity"]
    role: str
    label: str
    raw_value: str
    normalized_value: str
    is_partial: bool = False
    currency: str | None = None
    numeric_amount: float | None = None
    evidence_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    quote: str | None = None
    specialist: ReviewReportSpecialistName | None = None
    output_path: str | None = None
    from_claim_context: bool = False
    verification_status: str | None = None


def content_tokens(text: str) -> set[str]:
    """Return meaningful lowercase tokens from text for relevance matching."""
    raw = re.findall(r"[a-z0-9]{3,}", text.casefold())
    return {tok for tok in raw if tok not in _STOPWORDS}


def check_statement_supports_reference(
    statement: str,
    explanation: str,
    reference_text: str,
) -> bool:
    """Return True if statement is genuinely supported by reference_text."""
    stmt_norm = " ".join(statement.casefold().split())
    ref_norm = " ".join(reference_text.casefold().split())
    if not ref_norm or not stmt_norm:
        return False
    if stmt_norm == ref_norm or stmt_norm in ref_norm or ref_norm in stmt_norm:
        return True

    stmt_tokens = content_tokens(statement)
    ref_tokens = content_tokens(reference_text)
    if not stmt_tokens or not ref_tokens:
        return False
    shared = stmt_tokens & ref_tokens
    if not shared:
        return False
    overlap_ratio = len(shared) / min(len(stmt_tokens), len(ref_tokens))
    return overlap_ratio >= 0.34 or len(shared) >= 2


def index_specialist_findings(
    report_input: ReviewReportInput,
) -> list[IndexedSpecialistFinding]:
    """Build a canonical ordered list of all findings across completed specialists."""
    indexed: list[IndexedSpecialistFinding] = []

    for spec_name in CANONICAL_SPECIALISTS:
        spec_input = getattr(report_input, spec_name, None)
        if spec_input is None or spec_input.status not in {
            "completed",
            "insufficient_evidence",
        }:
            continue
        analysis = spec_input.analysis
        if not isinstance(analysis, dict):
            continue

        if spec_name == "intake_agent":
            for idx, item in enumerate(analysis.get("extracted_fields", [])):
                if isinstance(item, dict):
                    val = item.get("value")
                    fname = item.get("field_name")
                    ev_ids = tuple(
                        str(e) for e in item.get("source_evidence_ids", []) if e
                    )
                    if isinstance(val, str) and val.strip():
                        indexed.append(
                            IndexedSpecialistFinding(
                                specialist=spec_name,
                                output_path=f"/extracted_fields/{idx}/value",
                                finding_text=val.strip(),
                                explanation_text=str(fname or ""),
                                evidence_ids=ev_ids,
                                category="extracted_field",
                            )
                        )
            for idx, item in enumerate(analysis.get("document_flags", [])):
                if isinstance(item, dict):
                    desc = item.get("description")
                    ev_ids = tuple(
                        str(e) for e in item.get("source_evidence_ids", []) if e
                    )
                    if isinstance(desc, str) and desc.strip():
                        indexed.append(
                            IndexedSpecialistFinding(
                                specialist=spec_name,
                                output_path=f"/document_flags/{idx}/description",
                                finding_text=desc.strip(),
                                evidence_ids=ev_ids,
                                category="flag",
                            )
                        )
            for idx, val in enumerate(analysis.get("missing_information", [])):
                if isinstance(val, str) and val.strip():
                    indexed.append(
                        IndexedSpecialistFinding(
                            specialist=spec_name,
                            output_path=f"/missing_information/{idx}",
                            finding_text=val.strip(),
                            category="missing_information",
                        )
                    )

        elif spec_name == "evidence_analyst":
            for list_key, cat in (
                ("factual_findings", "fact"),
                ("inconsistencies", "inconsistency"),
            ):
                for idx, item in enumerate(analysis.get(list_key, [])):
                    if isinstance(item, dict):
                        f_txt = item.get("finding")
                        e_txt = item.get("explanation")
                        ev_ids = tuple(
                            str(e)
                            for e in item.get("supporting_evidence_ids", [])
                            if e
                        )
                        if isinstance(f_txt, str) and f_txt.strip():
                            indexed.append(
                                IndexedSpecialistFinding(
                                    specialist=spec_name,
                                    output_path=f"/{list_key}/{idx}/finding",
                                    finding_text=f_txt.strip(),
                                    explanation_text=(
                                        e_txt.strip()
                                        if isinstance(e_txt, str)
                                        else ""
                                    ),
                                    evidence_ids=ev_ids,
                                    category=cat,
                                )
                            )
            for idx, val in enumerate(analysis.get("missing_information", [])):
                if isinstance(val, str) and val.strip():
                    indexed.append(
                        IndexedSpecialistFinding(
                            specialist=spec_name,
                            output_path=f"/missing_information/{idx}",
                            finding_text=val.strip(),
                            category="missing_information",
                        )
                    )

        elif spec_name == "policy_analyst":
            for list_key in (
                "relevant_clauses",
                "exclusions",
                "limits_and_deductibles",
            ):
                for idx, item in enumerate(analysis.get(list_key, [])):
                    if isinstance(item, dict):
                        f_txt = item.get("finding") or item.get("explanation")
                        e_txt = item.get("explanation") or ""
                        ev_ids = tuple(
                            str(e)
                            for e in item.get("supporting_evidence_ids", [])
                            if e
                        )
                        path_field = (
                            "finding"
                            if isinstance(item.get("finding"), str)
                            and item.get("finding").strip()
                            else "explanation"
                        )
                        if isinstance(f_txt, str) and f_txt.strip():
                            indexed.append(
                                IndexedSpecialistFinding(
                                    specialist=spec_name,
                                    output_path=f"/{list_key}/{idx}/{path_field}",
                                    finding_text=f_txt.strip(),
                                    explanation_text=(
                                        e_txt.strip()
                                        if isinstance(e_txt, str)
                                        else ""
                                    ),
                                    evidence_ids=ev_ids,
                                    category="policy_clause",
                                )
                            )
            for idx, val in enumerate(analysis.get("missing_information", [])):
                if isinstance(val, str) and val.strip():
                    indexed.append(
                        IndexedSpecialistFinding(
                            specialist=spec_name,
                            output_path=f"/missing_information/{idx}",
                            finding_text=val.strip(),
                            category="missing_information",
                        )
                    )

        elif spec_name == "repair_estimate_analyst":
            for idx, item in enumerate(analysis.get("findings", [])):
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("title")
                    ev_ids = tuple(
                        str(e) for e in item.get("source_evidence_ids", []) if e
                    )
                    path_field = (
                        "description"
                        if isinstance(item.get("description"), str)
                        and item.get("description").strip()
                        else "title"
                    )
                    if isinstance(desc, str) and desc.strip():
                        indexed.append(
                            IndexedSpecialistFinding(
                                specialist=spec_name,
                                output_path=f"/findings/{idx}/{path_field}",
                                finding_text=desc.strip(),
                                evidence_ids=ev_ids,
                                category="repair_finding",
                            )
                        )
            for idx, item in enumerate(analysis.get("line_items", [])):
                if isinstance(item, dict):
                    desc = item.get("description")
                    ev_ids = tuple(
                        str(e) for e in item.get("source_evidence_ids", []) if e
                    )
                    if isinstance(desc, str) and desc.strip():
                        indexed.append(
                            IndexedSpecialistFinding(
                                specialist=spec_name,
                                output_path=f"/line_items/{idx}/description",
                                finding_text=desc.strip(),
                                evidence_ids=ev_ids,
                                category="repair_line_item",
                            )
                        )
            for idx, val in enumerate(analysis.get("missing_information", [])):
                if isinstance(val, str) and val.strip():
                    indexed.append(
                        IndexedSpecialistFinding(
                            specialist=spec_name,
                            output_path=f"/missing_information/{idx}",
                            finding_text=val.strip(),
                            category="missing_information",
                        )
                    )

        elif spec_name == "risk_anomaly_agent":
            for list_key, cat in (
                ("observed_facts", "fact"),
                ("anomalies", "anomaly"),
                ("hypotheses", "hypothesis"),
                ("missing_information", "missing_information"),
            ):
                for idx, item in enumerate(analysis.get(list_key, [])):
                    if isinstance(item, dict):
                        f_txt = item.get("finding") or item.get("explanation")
                        e_txt = item.get("explanation") or ""
                        ev_ids = tuple(
                            str(e)
                            for e in item.get("supporting_evidence_ids", [])
                            if e
                        )
                        path_field = (
                            "finding"
                            if isinstance(item.get("finding"), str)
                            and item.get("finding").strip()
                            else "explanation"
                        )
                        if isinstance(f_txt, str) and f_txt.strip():
                            indexed.append(
                                IndexedSpecialistFinding(
                                    specialist=spec_name,
                                    output_path=f"/{list_key}/{idx}/{path_field}",
                                    finding_text=f_txt.strip(),
                                    explanation_text=(
                                        e_txt.strip()
                                        if isinstance(e_txt, str)
                                        else ""
                                    ),
                                    evidence_ids=ev_ids,
                                    category=cat,
                                )
                            )
                    elif isinstance(item, str) and item.strip():
                        indexed.append(
                            IndexedSpecialistFinding(
                                specialist=spec_name,
                                output_path=f"/{list_key}/{idx}",
                                finding_text=item.strip(),
                                category=cat,
                            )
                        )

    return indexed


def resolve_true_originating_specialist(
    item: ReviewReportItem,
    indexed_findings: list[IndexedSpecialistFinding],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
) -> tuple[str | None, Literal["verified", "unverified", "system_derived"]]:
    """Determine the true originating specialist or system component for a report item.

    Never assigns a finding to a downstream specialist (e.g. risk_anomaly_agent)
    merely because it echoed an upstream specialist's finding.
    """
    upstream_specialists = {
        "intake_agent",
        "evidence_analyst",
        "policy_analyst",
        "repair_estimate_analyst",
    }

    # 1. If the item cites analyst_output_references, check if any upstream specialist
    # originated the finding before a downstream aggregator (like risk_anomaly_agent).
    if item.analyst_output_references:
        ref_specs = [ref.specialist for ref in item.analyst_output_references]
        for spec in CANONICAL_SPECIALISTS:
            if spec in upstream_specialists and spec in ref_specs:
                return spec, "verified"

        # If only risk_anomaly_agent is referenced, check if the same finding
        # actually originated in an upstream specialist!
        if all(spec == "risk_anomaly_agent" for spec in ref_specs):
            stmt_tokens = content_tokens(item.statement)
            item_ev_ids = set(item.supporting_evidence_ids)
            for upstream in indexed_findings:
                if upstream.specialist not in upstream_specialists:
                    continue
                up_tokens = content_tokens(upstream.finding_text)
                if not stmt_tokens or not up_tokens:
                    continue
                shared = stmt_tokens & up_tokens
                overlap = len(shared) / min(len(stmt_tokens), len(up_tokens))
                same_ev = bool(
                    item_ev_ids
                    and upstream.evidence_ids
                    and (item_ev_ids & set(upstream.evidence_ids))
                )
                if overlap >= 0.6 or (overlap >= 0.4 and same_ev):
                    return upstream.specialist, "verified"
            return "risk_anomaly_agent", "verified"

    # 2. If the item is backed directly by retrieved_evidence, trace which
    # upstream specialist extracted that fact or attribute to evidence retrieval.
    if item.supporting_evidence_ids:
        valid_ev = [
            eid for eid in item.supporting_evidence_ids if eid in evidence_by_id
        ]
        if not valid_ev:
            return None, "unverified"
        stmt_tokens = content_tokens(item.statement)
        valid_ev_set = set(valid_ev)
        best_match: IndexedSpecialistFinding | None = None
        best_score = 0.0
        for cand in indexed_findings:
            if not (valid_ev_set & set(cand.evidence_ids)):
                continue
            cand_tokens = content_tokens(cand.finding_text)
            if not stmt_tokens or not cand_tokens:
                continue
            score = len(stmt_tokens & cand_tokens) / min(
                len(stmt_tokens), len(cand_tokens)
            )
            # Prefer upstream specialists over risk_anomaly_agent on ties
            if cand.specialist in upstream_specialists:
                score += 0.05
            if score > best_score and score >= 0.35:
                best_score = score
                best_match = cand
        if best_match is not None:
            return best_match.specialist, "verified"

        # Check if all cited chunks are policy chunks or repair estimate chunks
        chunks = [evidence_by_id[eid] for eid in valid_ev]
        if all(
            getattr(c, "clause_identifier", None) is not None
            or "policy" in c.filename.lower()
            for c in chunks
        ):
            return "policy_evidence_retrieval", "system_derived"
        return "evidence_retrieval", "system_derived"

    # 3. Conflict assertions with sources or analyst references
    if item.conflicting_assertions:
        for assertion in item.conflicting_assertions:
            if assertion.analyst_output_reference is not None:
                return assertion.analyst_output_reference.specialist, "verified"
            if assertion.source is not None and assertion.source.evidence_id in evidence_by_id:
                return "cross_source_validation", "system_derived"

    return None, "unverified"


def validate_and_attribute_items(
    items: list[ReviewReportItem],
    *,
    category: str,
    indexed_findings: list[IndexedSpecialistFinding],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
    used_references: dict[tuple[str, str], str],
    warnings: list[str],
) -> list[ReviewReportItem]:
    """Validate source attribution on each report item and populate originating_specialist."""
    validated: list[ReviewReportItem] = []
    finding_lookup = {
        (f.specialist, f.output_path): f for f in indexed_findings
    }

    for item in items:
        originating_spec, attr_status = resolve_true_originating_specialist(
            item, indexed_findings, evidence_by_id
        )
        updated_limitation = item.limitation

        # Check reference support & prevent reusing the same reference for an unrelated statement
        for ref in item.analyst_output_references:
            ref_key = (ref.specialist, ref.output_path)
            indexed_ref = finding_lookup.get(ref_key)
            if indexed_ref is None:
                attr_status = "unverified"
                warnings.append(
                    f"Unverified specialist reference {ref.specialist}:{ref.output_path} in {category}."
                )
                continue

            if category != "conflicting_findings" and not check_statement_supports_reference(
                item.statement, item.explanation, ref.finding_text
            ):
                attr_status = "unverified"
                warnings.append(
                    f"Cited finding {ref.specialist}:{ref.output_path} does not support statement in {category}."
                )

            prior_stmt = used_references.get(ref_key)
            if prior_stmt is not None:
                prior_tokens = content_tokens(prior_stmt)
                curr_tokens = content_tokens(item.statement)
                if prior_tokens and curr_tokens and not (prior_tokens & curr_tokens):
                    attr_status = "unverified"
                    warnings.append(
                        f"Specialist reference {ref.specialist}:{ref.output_path} was reused for an unrelated statement."
                    )
            else:
                used_references[ref_key] = item.statement

        if attr_status == "unverified":
            unverified_note = "Source attribution is unverified and requires human review."
            if not updated_limitation:
                updated_limitation = unverified_note
            elif "unverified" not in updated_limitation.casefold():
                updated_limitation = f"{updated_limitation} {unverified_note}"

        validated.append(
            item.model_copy(
                update={
                    "originating_specialist": originating_spec,
                    "attribution_status": attr_status,
                    "limitation": updated_limitation,
                }
            )
        )
    return validated


# ---------------------------------------------------------------------------
# Requirement 4: Global Date, Amount, and Entity Extraction & Validation
# ---------------------------------------------------------------------------

_DATE_ROLE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "incident_date",
        "Incident / Loss Date",
        re.compile(
            r"\b(?:incident\s+date|date\s+of\s+incident|loss\s+date|date\s+of\s+loss|accident\s+date|date\s+of\s+accident)\s*[:=-]?\s*(?:is\s+(?:recorded\s+as\s+)?)?([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "inspection_date",
        "Inspection / Survey Date",
        re.compile(
            r"\b(?:inspection\s+date|date\s+of\s+inspection|survey\s+date|date\s+of\s+survey)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "admission_date",
        "Admission Date",
        re.compile(
            r"\b(?:admission\s+date|date\s+of\s+admission|admitted\s+on)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "discharge_date",
        "Discharge Date",
        re.compile(
            r"\b(?:discharge\s+date|date\s+of\s+discharge|discharged\s+on)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "document_date",
        "Document / Bill Date",
        re.compile(
            r"\b(?:invoice\s+date|bill\s+date|estimate\s+date|report\s+date|document\s+date)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "policy_effective_from",
        "Policy Effective From",
        re.compile(
            r"\b(?:effective\s+from|policy\s+start\s+date|valid\s+from)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=\s+to\b|[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "policy_effective_to",
        "Policy Effective To",
        re.compile(
            r"\b(?:effective\s+to|policy\s+expiry\s+date|valid\s+until|valid\s+upto)\s*[:=-]?\s*([A-Za-z0-9,/\s-]{4,30}?)(?=[.;|\n]|$)",
            re.IGNORECASE,
        ),
    ),
)

_FULL_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_FULL_DMY_SLASH_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_FULL_DMY_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,]?\s+(\d{4})\b",
    re.IGNORECASE,
)
_FULL_MDY_TEXT_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})[,]?\s+(\d{4})\b",
    re.IGNORECASE,
)

# Partial date patterns (no year or no day)
_PARTIAL_DM_TEXT_RE = re.compile(
    r"^\s*(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*$",
    re.IGNORECASE,
)
_PARTIAL_MD_TEXT_RE = re.compile(
    r"^\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})\s*$",
    re.IGNORECASE,
)
_PARTIAL_MY_TEXT_RE = re.compile(
    r"^\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,]?\s+(\d{4})\s*$",
    re.IGNORECASE,
)
_PARTIAL_DM_SLASH_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")
_PARTIAL_YM_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{2})\s*$")


def parse_date_string(raw: str) -> tuple[str, str, bool] | None:
    """Parse a date string into (clean_raw, normalized_canonical, is_partial).

    Never infers a missing year or day; preserves partial dates as partial.
    """
    candidate = raw.strip().rstrip(".,;|")
    # Strip trailing time or parenthetical notes
    candidate = re.sub(r"\s*\([^)]*\)\s*$", "", candidate).strip()
    candidate = re.sub(r"\s+at\s+\d{1,2}:\d{2}.*$", "", candidate, flags=re.IGNORECASE).strip()

    m = _FULL_ISO_DATE_RE.search(candidate)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return m.group(0), f"{y:04d}-{mo:02d}-{d:02d}", False

    m = _FULL_DMY_TEXT_RE.search(candidate)
    if m:
        d = int(m.group(1))
        mo = _MONTH_MAP[m.group(2).casefold()[:3]]
        y = int(m.group(3))
        return m.group(0), f"{y:04d}-{mo:02d}-{d:02d}", False

    m = _FULL_MDY_TEXT_RE.search(candidate)
    if m:
        mo = _MONTH_MAP[m.group(1).casefold()[:3]]
        d = int(m.group(2))
        y = int(m.group(3))
        return m.group(0), f"{y:04d}-{mo:02d}-{d:02d}", False

    m = _FULL_DMY_SLASH_RE.search(candidate)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return m.group(0), f"{y:04d}-{mo:02d}-{d:02d}", False

    # Partial dates (exact match on candidate after trimming)
    m = _PARTIAL_DM_TEXT_RE.match(candidate)
    if m:
        d = int(m.group(1))
        mo = _MONTH_MAP[m.group(2).casefold()[:3]]
        return candidate, f"PARTIAL:--{mo:02d}-{d:02d}", True

    m = _PARTIAL_MD_TEXT_RE.match(candidate)
    if m:
        mo = _MONTH_MAP[m.group(1).casefold()[:3]]
        d = int(m.group(2))
        return candidate, f"PARTIAL:--{mo:02d}-{d:02d}", True

    m = _PARTIAL_MY_TEXT_RE.match(candidate)
    if m:
        mo = _MONTH_MAP[m.group(1).casefold()[:3]]
        y = int(m.group(2))
        return candidate, f"PARTIAL:{y:04d}-{mo:02d}--", True

    m = _PARTIAL_DM_SLASH_RE.match(candidate)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        return candidate, f"PARTIAL:--{mo:02d}-{d:02d}", True

    m = _PARTIAL_YM_ISO_RE.match(candidate)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return candidate, f"PARTIAL:{y:04d}-{mo:02d}--", True

    return None


_AMOUNT_ROLE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "idv",
        "Insured Declared Value (IDV)",
        re.compile(
            r"(?:insured\s+declared\s+value(?:\s*\(idv\))?|\bidv\b)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "sum_insured",
        "Sum Insured",
        re.compile(
            r"(?:base\s+sum\s+insured|annual\s+sum\s+insured|sum\s+insured|annual\s+coverage\s+limit)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "repair_estimate",
        "Repair Estimate Amount",
        re.compile(
            r"(?:total\s+repair\s+estimate|estimated\s+repair\s+cost|repair\s+estimate(?:\s+total|\s+amount)?|net\s+repair\s+estimate)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "deductible",
        "Deductible",
        re.compile(
            r"(?:compulsory\s+deductible|policy\s+deductible|deductible\s+amount)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "medical_expenses",
        "Medical / Hospital Bill Amount",
        re.compile(
            r"(?:total\s+medical\s+expenses|final\s+hospital\s+bill|hospital\s+bill\s+total|total\s+bill\s+amount)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "claimed_amount",
        "Claimed Amount",
        re.compile(
            r"(?:total\s+claim\s+amount|claimed\s+amount|amount\s+claimed)\s*[:=-]?\s*(INR|Rs\.?|₹|USD|\$|EUR|€|GBP|£)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            re.IGNORECASE,
        ),
    ),
)

_ENTITY_ROLE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "policy_identifier",
        "Policy Identifier",
        re.compile(
            r"\bpolicy\s*(?:number|id|identifier|no\.?)\s*[:=-]\s*([A-Z0-9][A-Z0-9_-]{4,45})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "claim_number",
        "Claim Identifier",
        re.compile(
            r"\bclaim\s*(?:number|id|no\.?|ref)\s*[:=-]\s*([A-Z0-9][A-Z0-9_-]{4,45})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "registration_number",
        "Vehicle Registration Number",
        re.compile(
            r"\b(?:vehicle\s+)?registration\s*(?:number|no\.?)\s*[:=-]\s*([A-Z]{2}[-\s]?\d{1,2}[-\s]?[A-Z]{1,3}[-\s]?\d{3,4})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "claimant_name",
        "Claimant / Insured Name",
        re.compile(
            r"\b(?:claimant|insured|policyholder|patient)\s+name\s*[:=-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})(?=[.,;|\n]|$)",
        ),
    ),
    (
        "hospital_name",
        "Hospital / Facility Name",
        re.compile(
            r"\b(?:hospital|medical\s+center|treating\s+hospital)\s+name\s*[:=-]\s*([A-Z][A-Za-z0-9\s&.'-]{3,50}?)(?=[.,;|\n]|$)",
        ),
    ),
)


def _normalize_currency(raw_curr: str) -> str:
    c = raw_curr.strip()
    if c in {"₹", "Rs", "Rs.", "rs", "rs.", "INR", "inr"}:
        return "INR"
    if c in {"$", "USD", "usd"}:
        return "USD"
    if c in {"€", "EUR", "eur"}:
        return "EUR"
    if c in {"£", "GBP", "gbp"}:
        return "GBP"
    return c.upper()


def _extract_values_from_chunks(
    chunks: list[ReviewReportEvidenceChunk],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
) -> list[ExtractedStructuredValue]:
    """Extract role-classified dates, amounts, and entities from retrieved chunks."""
    extracted: list[ExtractedStructuredValue] = []
    for ev in chunks:
        if ev.chunk_id not in evidence_by_id:
            continue
        text = ev.text
        v_status = getattr(ev, "verification_status", None)

        # Dates
        for role, label, pattern in _DATE_ROLE_PATTERNS:
            for match in pattern.finditer(text):
                parsed = parse_date_string(match.group(1))
                if parsed is None:
                    continue
                clean_raw, norm_date, is_partial = parsed
                quote = match.group(0).strip()
                if len(quote) >= 8 and quote_matches_evidence(quote, text):
                    extracted.append(
                        ExtractedStructuredValue(
                            kind="date",
                            role=role,
                            label=label,
                            raw_value=clean_raw,
                            normalized_value=norm_date,
                            is_partial=is_partial,
                            evidence_id=ev.chunk_id,
                            document_id=str(ev.document_id),
                            filename=ev.filename,
                            page_number=ev.page_number,
                            quote=quote,
                            verification_status=v_status,
                        )
                    )

        # Amounts
        for role, label, pattern in _AMOUNT_ROLE_PATTERNS:
            for match in pattern.finditer(text):
                raw_curr = match.group(1).strip()
                raw_num = match.group(2).strip()
                try:
                    num_val = float(raw_num.replace(",", ""))
                except ValueError:
                    continue
                norm_curr = _normalize_currency(raw_curr)
                display_val = f"{raw_curr} {raw_num}"
                quote = match.group(0).strip()
                if len(quote) >= 8 and quote_matches_evidence(quote, text):
                    extracted.append(
                        ExtractedStructuredValue(
                            kind="amount",
                            role=role,
                            label=label,
                            raw_value=display_val,
                            normalized_value=f"{norm_curr}:{num_val:.2f}",
                            currency=norm_curr,
                            numeric_amount=num_val,
                            evidence_id=ev.chunk_id,
                            document_id=str(ev.document_id),
                            filename=ev.filename,
                            page_number=ev.page_number,
                            quote=quote,
                            verification_status=v_status,
                        )
                    )

        # Entities
        for role, label, pattern in _ENTITY_ROLE_PATTERNS:
            for match in pattern.finditer(text):
                raw_ent = match.group(1).strip()
                norm_ent = re.sub(r"[\s-]+", "-", raw_ent.upper())
                quote = match.group(0).strip()
                if len(quote) >= 8 and quote_matches_evidence(quote, text):
                    extracted.append(
                        ExtractedStructuredValue(
                            kind="entity",
                            role=role,
                            label=label,
                            raw_value=raw_ent,
                            normalized_value=norm_ent,
                            evidence_id=ev.chunk_id,
                            document_id=str(ev.document_id),
                            filename=ev.filename,
                            page_number=ev.page_number,
                            quote=quote,
                            verification_status=v_status,
                        )
                    )

    return extracted


def extract_structured_values(
    report_input: ReviewReportInput,
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
) -> list[ExtractedStructuredValue]:
    """Extract role-classified dates, amounts, and entities from evidence and context."""
    return _extract_values_from_chunks(report_input.retrieved_evidence, evidence_by_id)


def detect_cross_source_discrepancies(
    extracted_values: list[ExtractedStructuredValue],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
) -> tuple[list[ReviewReportItem], list[ReviewReportItem]]:
    """Detect cross-source conflicts for the same semantic role without conflating distinct roles.

    Returns (discrepancy_observed_facts, discrepancy_conflicts).
    """
    by_role: dict[tuple[str, str], list[ExtractedStructuredValue]] = {}
    for val in extracted_values:
        if val.is_partial:
            # Partial values are incomplete, not contradictory against complete values of the same date
            continue
        if val.evidence_id and val.evidence_id in evidence_by_id and val.quote:
            by_role.setdefault((val.kind, val.role), []).append(val)

    facts: list[ReviewReportItem] = []
    conflicts: list[ReviewReportItem] = []

    for (kind, role), items in by_role.items():
        # Group by normalized_value keeping distinct first occurrence
        distinct_by_norm: dict[str, ExtractedStructuredValue] = {}
        for item in items:
            if item.normalized_value not in distinct_by_norm:
                distinct_by_norm[item.normalized_value] = item
        if len(distinct_by_norm) < 2:
            continue

        distinct_items = list(distinct_by_norm.values())
        label = distinct_items[0].label

        # Preserve each distinct source value as an observed_fact
        for item in distinct_items:
            ev = evidence_by_id[item.evidence_id]  # type: ignore[index]
            is_policy_unverified = (
                getattr(ev, "clause_identifier", None) is not None
                or "policy" in ev.filename.lower()
            ) and getattr(ev, "verification_status", None) != "verified"
            lim = (
                "Policy passage is marked pending_review and awaits human verification."
                if is_policy_unverified
                else None
            )
            origin_spec = (
                "policy_evidence_retrieval"
                if (
                    getattr(ev, "clause_identifier", None) is not None
                    or "policy" in ev.filename.lower()
                )
                else "evidence_retrieval"
            )
            facts.append(
                ReviewReportItem(
                    statement=item.quote or f"{label}: {item.raw_value}",
                    explanation=(
                        f"{label} value ({item.raw_value}) extracted from "
                        f"{item.filename} (page {item.page_number})."
                    ),
                    supporting_evidence_ids=[ev.chunk_id],
                    supporting_quotes=[
                        ReviewReportEvidenceQuote(
                            evidence_id=ev.chunk_id,
                            quote=item.quote or item.raw_value,
                        )
                    ],
                    sources=[
                        ReviewReportSourceReference(
                            evidence_id=ev.chunk_id,
                            document_id=str(ev.document_id),
                            filename=ev.filename,
                            page_number=ev.page_number,
                        )
                    ],
                    source_basis="retrieved_evidence",
                    limitation=lim,
                    originating_specialist=origin_spec,
                    attribution_status="system_derived",
                )
            )

        first, second = distinct_items[0], distinct_items[1]
        ev1 = evidence_by_id[first.evidence_id]  # type: ignore[index]
        ev2 = evidence_by_id[second.evidence_id]  # type: ignore[index]
        evidence_ids = [ev1.chunk_id]
        if ev2.chunk_id != ev1.chunk_id:
            evidence_ids.append(ev2.chunk_id)

        quotes = [
            ReviewReportEvidenceQuote(
                evidence_id=ev1.chunk_id,
                quote=first.quote or first.raw_value,
            )
        ]
        if ev2.chunk_id != ev1.chunk_id:
            quotes.append(
                ReviewReportEvidenceQuote(
                    evidence_id=ev2.chunk_id,
                    quote=second.quote or second.raw_value,
                )
            )

        sources = [
            ReviewReportSourceReference(
                evidence_id=eid,
                document_id=str(evidence_by_id[eid].document_id),
                filename=evidence_by_id[eid].filename,
                page_number=evidence_by_id[eid].page_number,
            )
            for eid in evidence_ids
        ]

        subject_name = (
            "Vehicle / Policy Valuation"
            if role == "idv"
            else "Policy Coverage"
            if role in {"sum_insured", "deductible", "policy_identifier"}
            else "Claim Chronology"
            if kind == "date"
            else "Claim Financial Valuation"
            if kind == "amount"
            else "Claim Entity Record"
        )

        conflicts.append(
            ReviewReportItem(
                statement=(
                    f"{label} differs across retrieved sources: "
                    f"{first.raw_value} in {first.filename} versus "
                    f"{second.raw_value} in {second.filename}."
                ),
                explanation=(
                    f"Retrieved source {first.filename} (page {first.page_number}) "
                    f"records {label} as {first.raw_value}, whereas "
                    f"{second.filename} (page {second.page_number}) records {label} "
                    f"as {second.raw_value}. Both values are preserved for mandatory human verification."
                ),
                supporting_evidence_ids=evidence_ids,
                supporting_quotes=quotes,
                sources=sources,
                conflicting_assertions=[
                    ReviewReportConflictAssertion(
                        assertion=first.quote or first.raw_value,
                        subject=subject_name,
                        attribute=label,
                        value=first.raw_value,
                        source=ReviewReportSourceReference(
                            evidence_id=ev1.chunk_id,
                            document_id=str(ev1.document_id),
                            filename=ev1.filename,
                            page_number=ev1.page_number,
                        ),
                    ),
                    ReviewReportConflictAssertion(
                        assertion=second.quote or second.raw_value,
                        subject=subject_name,
                        attribute=label,
                        value=second.raw_value,
                        source=ReviewReportSourceReference(
                            evidence_id=ev2.chunk_id,
                            document_id=str(ev2.document_id),
                            filename=ev2.filename,
                            page_number=ev2.page_number,
                        ),
                    ),
                ],
                source_basis="retrieved_evidence",
                limitation=(
                    f"Conflicting {label} values require human verification against "
                    "original policy and claim records."
                ),
                originating_specialist="cross_source_validation",
                attribution_status="system_derived",
            )
        )

    return facts, conflicts


def validate_partial_dates_in_report(
    items: list[ReviewReportItem],
    extracted_values: list[ExtractedStructuredValue],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
    warnings: list[str],
) -> list[ReviewReportItem]:
    """Ensure partial dates in evidence are never silently expanded with inferred years."""
    partial_dates = [
        v for v in extracted_values if v.kind == "date" and v.is_partial
    ]
    if not partial_dates:
        return items

    partial_by_ev: dict[str, list[ExtractedStructuredValue]] = {}
    for pv in partial_dates:
        if pv.evidence_id:
            partial_by_ev.setdefault(pv.evidence_id, []).append(pv)

    updated_items: list[ReviewReportItem] = []
    for item in items:
        modified = item
        for eid in item.supporting_evidence_ids:
            if eid not in partial_by_ev or eid not in evidence_by_id:
                continue
            chunk_text = evidence_by_id[eid].text
            for pv in partial_by_ev[eid]:
                # Check if statement contains the partial date AND adds a 4-digit year
                # that is not adjacent to that date in the source chunk
                if pv.raw_value.casefold() in item.statement.casefold():
                    years_in_stmt = re.findall(r"\b(19\d{2}|20\d{2})\b", item.statement)
                    for yr in years_in_stmt:
                        if f"{pv.raw_value} {yr}".casefold() in item.statement.casefold() or f"{pv.raw_value}, {yr}".casefold() in item.statement.casefold():
                            if f"{pv.raw_value} {yr}".casefold() not in chunk_text.casefold() and f"{pv.raw_value}, {yr}".casefold() not in chunk_text.casefold():
                                warnings.append(
                                    f"Statement inferred year {yr} for partial date '{pv.raw_value}' from {pv.filename}; preserved partial date."
                                )
                                clean_stmt = re.sub(
                                    rf"({re.escape(pv.raw_value)})[,]?\s+{yr}\b",
                                    r"\1",
                                    modified.statement,
                                    flags=re.IGNORECASE,
                                )
                                note = f"Source {pv.filename} contains only a partial date ('{pv.raw_value}'); missing year was not inferred."
                                lim = (
                                    f"{modified.limitation} {note}".strip()
                                    if modified.limitation
                                    else note
                                )
                                modified = modified.model_copy(
                                    update={"statement": clean_stmt, "limitation": lim}
                                )
        updated_items.append(modified)
    return updated_items


# ---------------------------------------------------------------------------
# Requirement 2: Global Missing-Information Reconciliation
# ---------------------------------------------------------------------------

_TOPIC_EVIDENCE_MATCHERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Vehicle Registration / Driving Licence (RC/DL)",
        (
            "registration certificate",
            "driving licence",
            "driving license",
            "driver license",
            "driver licence",
            "rc book",
            "rc and dl",
            "rc/dl",
            "registration number",
        ),
        (
            "rc_and_dl",
            "registration",
            "driving licence",
            "driving license",
            "dl no",
            "licence no",
            "registration no",
        ),
    ),
    (
        "Repair Estimate",
        (
            "repair estimate",
            "garage estimate",
            "workshop estimate",
            "parts and labor",
            "estimated repair",
        ),
        (
            "repair_estimate",
            "repair estimate",
            "parts",
            "labor",
            "estimate total",
            "bumper",
            "replacement",
        ),
    ),
    (
        "Damage Photographs",
        (
            "damage photo",
            "damage photograph",
            "vehicle photo",
            "inspection photo",
            "photographs of damage",
        ),
        (
            "damage_photo",
            "photo",
            "photograph",
            "visual inspection",
            "dent",
            "scratch",
        ),
    ),
    (
        "Incident / Accident Statement",
        (
            "incident statement",
            "accident statement",
            "claimant statement",
            "narration of incident",
            "incident report",
        ),
        (
            "incident_statement",
            "incident_report",
            "incident date",
            "accident",
            "occurred",
        ),
    ),
    (
        "Hospital Discharge Summary",
        (
            "discharge summary",
            "discharge note",
            "hospital discharge",
            "clinical summary",
        ),
        (
            "discharge_summary",
            "discharge",
            "admitted",
            "discharged",
            "diagnosis",
            "clinical course",
        ),
    ),
    (
        "Itemized Hospital Bill",
        (
            "itemized bill",
            "hospital bill",
            "final bill",
            "billing breakdown",
            "inpatient bill",
        ),
        (
            "itemized_bill",
            "hospital_bill",
            "breakdown of charges",
            "room & nursing",
            "room rent",
            "invoice",
        ),
    ),
    (
        "Policy Schedule / Wording",
        (
            "policy document",
            "policy schedule",
            "policy wording",
            "policy terms",
            "coverage terms",
            "policy copy",
        ),
        (
            "policy",
            "policy schedule",
            "sum insured",
            "insured declared value",
            "exclusions",
            "deductible",
        ),
    ),
)


def _claim_type_from_input(report_input: ReviewReportInput) -> str:
    ctx = report_input.structured_claim_context or report_input.claim_facts or {}
    raw = str(ctx.get("claim_type") or "").strip().lower()
    return raw


def reconcile_missing_information(
    report_input: ReviewReportInput,
    candidate_missing_items: list[ReviewReportItem],
    indexed_findings: list[IndexedSpecialistFinding],
    extracted_values: list[ExtractedStructuredValue],
    conflicts: list[ReviewReportItem],
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
    existing_report_statements: set[str] | None = None,
) -> tuple[list[ReviewReportItem], list[MissingInformationReconciliationItem]]:
    """Reconcile all missing-information candidates against available evidence and specialist outputs.

    Classifies each item into one of:
    - not_provided
    - not_retrieved
    - partially_available
    - retrieved_unverified
    - conflicting
    - not_applicable
    And removes false-positive 'missing' items when the information is already present in another source.
    """
    claim_type = _claim_type_from_input(report_input)
    reconciled_items: list[ReviewReportItem] = []
    reconciliation_log: list[MissingInformationReconciliationItem] = []
    seen_reconciliation_norms: set[str] = set()

    # Also gather any specialist missing_information items that were not yet in candidate_missing_items
    existing_norms = {
        " ".join(item.statement.casefold().split())
        for item in candidate_missing_items
    }
    if existing_report_statements:
        existing_norms.update(existing_report_statements)
    all_candidates: list[ReviewReportItem] = list(candidate_missing_items)
    for sf in indexed_findings:
        if sf.category == "missing_information":
            norm = " ".join(sf.finding_text.casefold().split())
            if norm not in existing_norms:
                existing_norms.add(norm)
                all_candidates.append(
                    ReviewReportItem(
                        statement=sf.finding_text,
                        explanation=f"Reported as missing by {sf.specialist}.",
                        analyst_output_references=[
                            ReviewReportAnalystOutputReference(
                                specialist=sf.specialist,
                                output_path=sf.output_path,
                                finding_text=sf.finding_text,
                            )
                        ],
                        source_basis="analyst_output",
                        limitation="This absence does not establish a negative conclusion and requires human verification.",
                        originating_specialist=sf.specialist,
                        attribution_status="verified",
                    )
                )

    policy_chunks = [
        ev
        for ev in report_input.retrieved_evidence
        if getattr(ev, "clause_identifier", None) is not None
        or "policy" in ev.filename.lower()
    ]
    has_unverified_policy = any(
        getattr(ev, "verification_status", None) != "verified"
        for ev in policy_chunks
    )

    conflict_text_blob = " ".join(
        f"{c.statement} {c.explanation}" for c in conflicts
    ).casefold()

    partial_values = [v for v in extracted_values if v.is_partial]

    for item in all_candidates:
        stmt_lower = item.statement.casefold()
        expl_lower = item.explanation.casefold()
        combined_lower = f"{stmt_lower} {expl_lower}"
        orig_spec = item.originating_specialist or (
            item.analyst_output_references[0].specialist
            if item.analyst_output_references
            else None
        )
        norm_key = " ".join(stmt_lower.split())
        if norm_key in seen_reconciliation_norms:
            continue
        seen_reconciliation_norms.add(norm_key)

        # Keep system fallback notices about unavailable synthesis / specialists
        if "consolidated ai report synthesis was unavailable" in stmt_lower:
            reconciled_items.append(
                item.model_copy(update={"missing_category": "not_retrieved"})
            )
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic="Specialist / Synthesis Execution Coverage",
                    original_statement=item.statement,
                    originating_specialist=orig_spec or "review_report_agent",
                    reconciled_category="not_retrieved",
                    retained_in_missing_information=True,
                    reconciliation_note="One or more AI specialists or report synthesis steps were unavailable.",
                )
            )
            continue

        # 1. Check domain applicability (not_applicable)
        if claim_type in {"health", "medical"} and any(
            kw in combined_lower for kw in _MOTOR_ONLY_KEYWORDS
        ):
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic="Motor-Specific Requirement on Health Claim",
                    original_statement=item.statement,
                    originating_specialist=orig_spec,
                    reconciled_category="not_applicable",
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        f"Item is not applicable to claim_type='{claim_type}' "
                        "and was excluded from missing information."
                    ),
                )
            )
            continue

        if claim_type in {"auto", "motor"} and any(
            kw in combined_lower for kw in _HEALTH_ONLY_KEYWORDS
        ):
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic="Health-Specific Requirement on Motor Claim",
                    original_statement=item.statement,
                    originating_specialist=orig_spec,
                    reconciled_category="not_applicable",
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        f"Item is not applicable to claim_type='{claim_type}' "
                        "and was excluded from missing information."
                    ),
                )
            )
            continue

        # 2. Check if this item relates to a known cross-source conflict (conflicting)
        item_tokens = content_tokens(item.statement)
        matched_conflict = next(
            (
                c
                for c in conflicts
                if item_tokens
                and len(item_tokens & content_tokens(c.statement)) >= 2
                and any(
                    tok in combined_lower
                    for tok in (
                        "idv",
                        "declared value",
                        "sum insured",
                        "incident date",
                        "loss date",
                        "admission date",
                        "discharge date",
                        "repair estimate",
                        "registration",
                        "policy number",
                        "conflict",
                        "discrepancy",
                        "mismatch",
                    )
                )
            ),
            None,
        )
        if matched_conflict is not None:
            src_names = list({s.filename for s in matched_conflict.sources})
            ev_ids = list(matched_conflict.supporting_evidence_ids)
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic="Conflicting Cross-Source Value",
                    original_statement=item.statement,
                    originating_specialist=orig_spec,
                    reconciled_category="conflicting",
                    available_in_sources=src_names,
                    supporting_evidence_ids=ev_ids,
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        "Multiple sources contain conflicting values for this item; "
                        "preserved in conflicting_findings for human verification."
                    ),
                )
            )
            continue

        # 3. Check if this item claims policy evidence is missing when policy chunks were retrieved
        is_policy_missing_claim = any(
            phrase in combined_lower
            for phrase in (
                "policy document",
                "policy schedule",
                "policy wording",
                "policy terms",
                "policy coverage",
                "policy copy",
                "policy clauses",
            )
        )
        if is_policy_missing_claim and policy_chunks:
            pol_filenames = sorted({ev.filename for ev in policy_chunks})
            pol_ev_ids = [ev.chunk_id for ev in policy_chunks]
            if has_unverified_policy:
                reconciliation_log.append(
                    MissingInformationReconciliationItem(
                        field_or_topic="Policy Schedule / Clauses",
                        original_statement=item.statement,
                        originating_specialist=orig_spec,
                        reconciled_category="retrieved_unverified",
                        available_in_sources=pol_filenames,
                        supporting_evidence_ids=pol_ev_ids,
                        retained_in_missing_information=False,
                        reconciliation_note=(
                            f"Policy evidence was retrieved from {', '.join(pol_filenames)} "
                            "with verification_status='pending_review'; classified as "
                            "retrieved_unverified rather than absent."
                        ),
                    )
                )
                continue
            else:
                reconciliation_log.append(
                    MissingInformationReconciliationItem(
                        field_or_topic="Policy Schedule / Clauses",
                        original_statement=item.statement,
                        originating_specialist=orig_spec,
                        reconciled_category="retrieved_unverified",
                        available_in_sources=pol_filenames,
                        supporting_evidence_ids=pol_ev_ids,
                        retained_in_missing_information=False,
                        reconciliation_note=(
                            f"Policy evidence was already retrieved in {', '.join(pol_filenames)}."
                        ),
                    )
                )
                continue

        # 4. Check if the item corresponds to a partial value (partially_available)
        matched_partial = next(
            (
                pv
                for pv in partial_values
                if pv.label.casefold() in combined_lower
                or pv.role.replace("_", " ") in combined_lower
                or (
                    "date" in combined_lower
                    and "year" in combined_lower
                    and pv.kind == "date"
                )
            ),
            None,
        )
        if matched_partial is not None:
            updated = item.model_copy(
                update={
                    "missing_category": "partially_available",
                    "limitation": (
                        f"Partial value ('{matched_partial.raw_value}') is available in "
                        f"{matched_partial.filename}; complete value requires human verification."
                    ),
                }
            )
            reconciled_items.append(updated)
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic=matched_partial.label,
                    original_statement=item.statement,
                    originating_specialist=orig_spec,
                    reconciled_category="partially_available",
                    available_in_sources=(
                        [matched_partial.filename]
                        if matched_partial.filename
                        else []
                    ),
                    supporting_evidence_ids=(
                        [matched_partial.evidence_id]
                        if matched_partial.evidence_id
                        else []
                    ),
                    extracted_value=matched_partial.raw_value,
                    retained_in_missing_information=True,
                    reconciliation_note=(
                        f"Only partial value '{matched_partial.raw_value}' is available "
                        f"in {matched_partial.filename}; missing components were not inferred."
                    ),
                )
            )
            continue

        # 5. Check if the item is ALREADY available in another retrieved source or completed specialist!
        matched_topic_label: str | None = None
        matched_chunks: list[ReviewReportEvidenceChunk] = []

        for topic_label, trigger_phrases, evidence_markers in _TOPIC_EVIDENCE_MATCHERS:
            if any(tp in combined_lower for tp in trigger_phrases):
                for ev in report_input.retrieved_evidence:
                    ev_haystack = f"{ev.filename} {ev.text}".casefold()
                    if any(em in ev_haystack for em in evidence_markers):
                        matched_chunks.append(ev)
                if matched_chunks:
                    matched_topic_label = topic_label
                    break

        # Also check if repair_estimate_analyst completed with line_items when repair estimate is claimed missing
        if (
            not matched_chunks
            and "repair estimate" in combined_lower
            and report_input.repair_estimate_analyst.status == "completed"
            and isinstance(report_input.repair_estimate_analyst.analysis, dict)
            and (
                report_input.repair_estimate_analyst.analysis.get("line_items")
                or report_input.repair_estimate_analyst.analysis.get("findings")
            )
        ):
            matched_topic_label = "Repair Estimate"
            matched_chunks = [
                ev
                for ev in report_input.retrieved_evidence
                if "estimate" in ev.filename.lower() or "repair" in ev.text.lower()
            ]

        # Also check if an extracted structured value (amount/date/entity) directly answers the missing item
        if not matched_chunks:
            for ev_val in extracted_values:
                if not ev_val.is_partial and ev_val.evidence_id in evidence_by_id:
                    role_words = ev_val.role.replace("_", " ")
                    if (
                        role_words in combined_lower
                        or ev_val.label.casefold() in combined_lower
                    ):
                        matched_topic_label = ev_val.label
                        matched_chunks = [evidence_by_id[ev_val.evidence_id]]
                        break

        if matched_topic_label is not None and matched_chunks:
            src_files = sorted({c.filename for c in matched_chunks})
            src_ev_ids = [c.chunk_id for c in matched_chunks]
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic=matched_topic_label,
                    original_statement=item.statement,
                    originating_specialist=orig_spec,
                    reconciled_category="retrieved_unverified",
                    available_in_sources=src_files,
                    supporting_evidence_ids=src_ev_ids,
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        f"Reconciled against available retrieved evidence in "
                        f"{', '.join(src_files)}; removed from missing_information."
                    ),
                )
            )
            continue

        # 6. Otherwise, the item is genuinely unavailable: classify as not_retrieved vs not_provided
        uploaded_match = next(
            (
                doc
                for doc in report_input.uploaded_documents
                if isinstance(doc, dict)
                and any(
                    tok in str(doc.get("filename", "")).casefold()
                    for tok in content_tokens(item.statement)
                )
            ),
            None,
        )
        any_specialist_unavailable = any(
            getattr(report_input, s).status in {"unavailable", "failed"}
            for s in CANONICAL_SPECIALISTS
        )
        if (
            uploaded_match is not None
            and "not retrieved" not in combined_lower
        ):
            category: MissingInformationCategory = "uploaded_not_retrieved"
            note = (
                "Document was uploaded to the claim record but was not "
                "retrieved into the active evidence context."
            )
        elif (
            uploaded_match is not None
            or report_input.evidence_retrieval_status in {"limited", "unavailable", "not_performed"}
            or ("retrieval" in combined_lower and "unavailable" in combined_lower)
            or (any_specialist_unavailable and "unavailable" in combined_lower)
        ):
            category = "not_retrieved"
            note = (
                "A potentially relevant document or retrieval channel exists "
                "but was not successfully retrieved."
            )
        else:
            category = "not_provided"
            note = "No supporting document or evidence was provided in the claim record."

        reconciled_items.append(
            item.model_copy(update={"missing_category": category})
        )
        reconciliation_log.append(
            MissingInformationReconciliationItem(
                field_or_topic=item.statement[:120],
                original_statement=item.statement,
                originating_specialist=orig_spec,
                reconciled_category=category,
                retained_in_missing_information=True,
                reconciliation_note=note,
            )
        )

    # Merge any pre-reconciled specialist items from shared_evidence_reconciliation
    if isinstance(report_input.structured_claim_context, Mapping):
        pre_reconciled = report_input.structured_claim_context.get(
            "shared_evidence_reconciliation"
        )
        if isinstance(pre_reconciled, list):
            existing_orig_norms = {
                " ".join(r.original_statement.casefold().split())
                for r in reconciliation_log
            }
            for raw_rec in pre_reconciled:
                if not isinstance(raw_rec, Mapping):
                    continue
                try:
                    rec_obj = MissingInformationReconciliationItem.model_validate(
                        dict(raw_rec)
                    )
                except Exception:
                    continue
                norm_orig = " ".join(rec_obj.original_statement.casefold().split())
                if norm_orig not in existing_orig_norms:
                    existing_orig_norms.add(norm_orig)
                    reconciliation_log.append(rec_obj)

    # Also ensure partial dates found in extracted_values are recorded in reconciliation_log if not already present
    for pv in partial_values:
        topic_key = f"partial:{pv.role}:{pv.raw_value}".casefold()
        if topic_key not in seen_reconciliation_norms:
            seen_reconciliation_norms.add(topic_key)
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic=pv.label,
                    original_statement=f"{pv.label} is only partially available as '{pv.raw_value}'.",
                    originating_specialist="evidence_retrieval",
                    reconciled_category="partially_available",
                    available_in_sources=[pv.filename] if pv.filename else [],
                    supporting_evidence_ids=[pv.evidence_id] if pv.evidence_id else [],
                    extracted_value=pv.raw_value,
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        f"Partial value '{pv.raw_value}' preserved from {pv.filename} "
                        "without inferring missing components."
                    ),
                )
            )

    # Also ensure unverified policy clauses are recorded in reconciliation_log if policy chunks are pending_review
    if policy_chunks and has_unverified_policy:
        pol_key = "policy:pending_review"
        if pol_key not in seen_reconciliation_norms:
            seen_reconciliation_norms.add(pol_key)
            pol_filenames = sorted({ev.filename for ev in policy_chunks})
            pol_ev_ids = [ev.chunk_id for ev in policy_chunks]
            reconciliation_log.append(
                MissingInformationReconciliationItem(
                    field_or_topic="Policy Clause Verification Status",
                    original_statement="Retrieved policy clauses are marked pending_review.",
                    originating_specialist="policy_analyst",
                    reconciled_category="retrieved_unverified",
                    available_in_sources=pol_filenames,
                    supporting_evidence_ids=pol_ev_ids,
                    retained_in_missing_information=False,
                    reconciliation_note=(
                        "Policy clauses were retrieved and used as supporting evidence, "
                        "but remain pending human verification."
                    ),
                )
            )

    return reconciled_items, reconciliation_log


# ---------------------------------------------------------------------------
# Requirement 3: Global Source Inventory & Shared Evidence Registry
# ---------------------------------------------------------------------------


def _infer_document_type(
    filename: str,
    chunks: list[ReviewReportEvidenceChunk],
) -> str:
    fname = filename.casefold()
    if any( getattr(c, "clause_identifier", None) is not None for c in chunks) or "policy" in fname:
        return "policy_document"
    if "estimate" in fname or "repair" in fname or "garage" in fname:
        return "repair_estimate"
    if "rc_and_dl" in fname or "licence" in fname or "license" in fname or "registration" in fname:
        return "registration_and_license"
    if "photo" in fname or "image" in fname or "damage" in fname:
        return "damage_photographs"
    if "discharge" in fname:
        return "discharge_summary"
    if "bill" in fname or "invoice" in fname or "receipt" in fname:
        return "itemized_bill"
    if "incident" in fname or "statement" in fname or "fir" in fname:
        return "incident_statement"
    if "diagnostic" in fname or "lab" in fname or "pathology" in fname:
        return "diagnostic_report"
    return "claim_evidence"


def build_source_inventory(
    report_input: ReviewReportInput,
    indexed_findings: list[IndexedSpecialistFinding],
    report_items: list[ReviewReportItem],
) -> list[ReportSourceInventoryItem]:
    """Build a deduplicated inventory of all documents retrieved or uploaded and track specialist usage.

    Never claims a specialist used a document unless there is concrete evidence of usage.
    """
    # Map chunk_id -> document_id and group chunks by document_id
    chunks_by_doc: dict[str, list[ReviewReportEvidenceChunk]] = {}
    doc_id_by_filename: dict[str, str] = {}
    chunk_to_doc: dict[str, str] = {}

    for ev in report_input.retrieved_evidence:
        doc_id = str(ev.document_id).strip()
        norm_fname = ev.filename.strip().casefold()
        if not doc_id:
            doc_id = f"doc:{norm_fname}"
        # Deduplicate if same filename was given a different synthetic doc_id only when doc_id is not UUID-distinct,
        # or group strictly by canonical document_id
        chunks_by_doc.setdefault(doc_id, []).append(ev)
        doc_id_by_filename.setdefault(norm_fname, doc_id)
        chunk_to_doc[str(ev.chunk_id)] = doc_id

    # Track which specialists actually cited each document_id
    specialists_by_doc: dict[str, set[str]] = {doc_id: set() for doc_id in chunks_by_doc}
    citations_by_doc: dict[str, int] = {doc_id: 0 for doc_id in chunks_by_doc}

    # 1. From indexed findings of completed specialists
    for sf in indexed_findings:
        for eid in sf.evidence_ids:
            doc_id = chunk_to_doc.get(str(eid))
            if doc_id is not None:
                specialists_by_doc.setdefault(doc_id, set()).add(sf.specialist)
                citations_by_doc[doc_id] = citations_by_doc.get(doc_id, 0) + 1

    # 2. Check explicit specialist_evidence_usage passed from graph state (e.g. repair_estimate_analyst)
    specialist_retrieved_docs: set[str] = set()
    for spec_name, ev_ids in (report_input.specialist_evidence_usage or {}).items():
        for eid in ev_ids:
            doc_id = chunk_to_doc.get(str(eid))
            if doc_id is not None:
                if spec_name == "repair_estimate_channel":
                    specialist_retrieved_docs.add(doc_id)
                elif hasattr(report_input, spec_name):
                    spec_obj = getattr(report_input, spec_name)
                    if spec_obj.status in {"completed", "insufficient_evidence"} and spec_obj.analysis:
                        specialists_by_doc.setdefault(doc_id, set()).add(spec_name)

    # 3. Also check if repair_estimate_analyst completed and a repair_estimate document exists
    if (
        report_input.repair_estimate_analyst.status in {"completed", "insufficient_evidence"}
        and isinstance(report_input.repair_estimate_analyst.analysis, dict)
    ):
        re_analysis = report_input.repair_estimate_analyst.analysis
        has_re_output = bool(
            re_analysis.get("line_items")
            or re_analysis.get("findings")
            or re_analysis.get("total_estimate") is not None
        )
        if has_re_output:
            for doc_id, doc_chunks in chunks_by_doc.items():
                if _infer_document_type(doc_chunks[0].filename, doc_chunks) == "repair_estimate":
                    specialists_by_doc.setdefault(doc_id, set()).add("repair_estimate_analyst")
                    specialist_retrieved_docs.add(doc_id)

    # 4. From intake_agent document_inventory (if intake_agent completed and cited source_evidence_ids)
    if (
        report_input.intake_agent.status in {"completed", "insufficient_evidence"}
        and isinstance(report_input.intake_agent.analysis, dict)
    ):
        for inv_item in report_input.intake_agent.analysis.get("document_inventory", []):
            if isinstance(inv_item, dict):
                for eid in inv_item.get("source_evidence_ids", []):
                    doc_id = chunk_to_doc.get(str(eid))
                    if doc_id is not None:
                        specialists_by_doc.setdefault(doc_id, set()).add("intake_agent")
                        citations_by_doc[doc_id] = citations_by_doc.get(doc_id, 0) + 1

    # 5. From final report items (review_report_agent citations)
    for r_item in report_items:
        for eid in r_item.supporting_evidence_ids:
            doc_id = chunk_to_doc.get(str(eid))
            if doc_id is not None:
                specialists_by_doc.setdefault(doc_id, set()).add("review_report_agent")
                citations_by_doc[doc_id] = citations_by_doc.get(doc_id, 0) + 1

    inventory: list[ReportSourceInventoryItem] = []
    seen_doc_ids: set[str] = set()

    for doc_id, doc_chunks in chunks_by_doc.items():
        seen_doc_ids.add(doc_id)
        first_chunk = doc_chunks[0]
        doc_type = _infer_document_type(first_chunk.filename, doc_chunks)
        ev_ids = list(dict.fromkeys(str(c.chunk_id) for c in doc_chunks))
        pages = sorted({int(c.page_number) for c in doc_chunks if c.page_number >= 1})
        ver_statuses = {
            str(getattr(c, "verification_status"))
            for c in doc_chunks
            if getattr(c, "verification_status", None) is not None
        }
        v_status = (
            "pending_review"
            if "pending_review" in ver_statuses
            else "verified"
            if "verified" in ver_statuses
            else None
        )
        proc_status: Literal[
            "processed",
            "pending_review",
            "verified",
            "uploaded",
            "failed",
            "unknown",
        ] = (
            "pending_review"
            if v_status == "pending_review"
            else "verified"
            if v_status == "verified"
            else "processed"
        )
        ret_status: Literal[
            "retrieved",
            "specialist_retrieved",
            "uploaded_not_retrieved",
            "not_retrieved",
        ] = (
            "specialist_retrieved"
            if doc_id in specialist_retrieved_docs
            else "retrieved"
        )

        doc_status: DocumentEvidenceStatus = (
            "verified"
            if v_status == "verified"
            else "retrieved_unverified"
        )

        ordered_used = [
            s
            for s in (*CANONICAL_SPECIALISTS, "review_report_agent")
            if s in specialists_by_doc.get(doc_id, set())
        ]

        inventory.append(
            ReportSourceInventoryItem(
                document_id=doc_id,
                filename=first_chunk.filename,
                document_type=doc_type,
                document_status=doc_status,
                processing_status=proc_status,
                retrieval_status=ret_status,
                used_by_specialists=ordered_used,
                evidence_ids=ev_ids,
                page_numbers=pages,
                citation_count=citations_by_doc.get(doc_id, 0),
                verification_status=v_status,
            )
        )

    # 6. Include uploaded documents that were NOT retrieved in retrieved_evidence
    for up_doc in report_input.uploaded_documents:
        if not isinstance(up_doc, dict):
            continue
        up_id = str(up_doc.get("document_id") or up_doc.get("id") or "").strip()
        up_fname = str(up_doc.get("filename") or "").strip()
        if not up_fname:
            continue
        if not up_id:
            up_id = doc_id_by_filename.get(up_fname.casefold(), f"uploaded:{up_fname.casefold()}")
        if up_id in seen_doc_ids or up_fname.casefold() in doc_id_by_filename:
            continue
        seen_doc_ids.add(up_id)
        raw_proc = str(up_doc.get("processing_status") or "uploaded").lower()
        proc_val: Literal[
            "processed",
            "pending_review",
            "verified",
            "uploaded",
            "failed",
            "unknown",
        ] = (
            raw_proc  # type: ignore[assignment]
            if raw_proc
            in {
                "processed",
                "pending_review",
                "verified",
                "uploaded",
                "failed",
                "unknown",
            }
            else "uploaded"
        )
        inventory.append(
            ReportSourceInventoryItem(
                document_id=up_id,
                filename=up_fname,
                document_type=str(
                    up_doc.get("document_type")
                    or _infer_document_type(up_fname, [])
                ),
                document_status="uploaded_not_retrieved",
                processing_status=proc_val,
                retrieval_status="uploaded_not_retrieved",
                used_by_specialists=[],
                evidence_ids=[],
                page_numbers=[],
                citation_count=0,
                verification_status=None,
            )
        )

    return inventory


# ---------------------------------------------------------------------------
# Requirement 5 & 6: Global Cross-Agent Report Validation & Transparency
# ---------------------------------------------------------------------------


def _compute_policy_verification_status(
    report_input: ReviewReportInput,
) -> Literal[
    "verified",
    "pending_review",
    "unverified",
    "not_retrieved",
    "not_applicable",
]:
    policy_chunks = [
        ev
        for ev in report_input.retrieved_evidence
        if getattr(ev, "clause_identifier", None) is not None
        or "policy" in ev.filename.lower()
    ]
    if not policy_chunks:
        if report_input.policy_analyst.status == "skipped":
            return "not_applicable"
        return "not_retrieved"

    statuses = {
        getattr(ev, "verification_status", None) for ev in policy_chunks
    }
    if "pending_review" in statuses:
        return "pending_review"
    if statuses == {"verified"}:
        return "verified"
    return "unverified"


def _compute_report_completeness(
    report: ReviewReportOutput,
    report_input: ReviewReportInput,
) -> Literal["complete", "partial", "insufficient_evidence"]:
    if report.overall_status == "insufficient_evidence":
        return "insufficient_evidence"
    if (
        report.overall_status == "incomplete"
        or report_input.evidence_retrieval_status != "completed"
        or any(
            getattr(report_input, s).status
            in {"unavailable", "failed", "pending", "insufficient_evidence"}
            for s in CANONICAL_SPECIALISTS
        )
    ):
        return "partial"
    return "complete"


def finalize_and_validate_report(
    report: ReviewReportOutput,
    report_input: ReviewReportInput,
    evidence_by_id: dict[str, ReviewReportEvidenceChunk],
) -> ReviewReportOutput:
    """Run global attribution, discrepancy detection, missing-info reconciliation,
    source inventory construction, and cross-agent validation on a report.
    """
    warnings: list[str] = list(report.validation_warnings)
    failures: list[str] = list(report.validation_failures)

    indexed_findings = index_specialist_findings(report_input)
    extracted_values = extract_structured_values(report_input, evidence_by_id)

    # 1. Detect deterministic cross-source discrepancies (dates, amounts, entities)
    disc_facts, disc_conflicts = detect_cross_source_discrepancies(
        extracted_values, evidence_by_id
    )

    observed_facts = list(report.observed_facts)
    existing_fact_norms = {
        " ".join(f.statement.casefold().split()) for f in observed_facts
    }
    for df in disc_facts:
        norm = " ".join(df.statement.casefold().split())
        if norm not in existing_fact_norms:
            existing_fact_norms.add(norm)
            observed_facts.append(df)

    conflicting_findings = list(report.conflicting_findings)
    existing_conflict_pairs: set[frozenset[str]] = set()
    for cf in conflicting_findings:
        vals = frozenset(a.value.casefold().strip() for a in cf.conflicting_assertions if a.value)
        if vals:
            existing_conflict_pairs.add(vals)

    for dc in disc_conflicts:
        dc_vals = frozenset(a.value.casefold().strip() for a in dc.conflicting_assertions if a.value)
        if dc_vals and dc_vals not in existing_conflict_pairs:
            existing_conflict_pairs.add(dc_vals)
            conflicting_findings.append(dc)

    # 2. Validate partial dates (ensure no inferred year/month on partial dates)
    observed_facts = validate_partial_dates_in_report(
        observed_facts, extracted_values, evidence_by_id, warnings
    )
    analyst_interpretations = validate_partial_dates_in_report(
        list(report.analyst_interpretations),
        extracted_values,
        evidence_by_id,
        warnings,
    )
    hypotheses = validate_partial_dates_in_report(
        list(report.hypotheses), extracted_values, evidence_by_id, warnings
    )

    # 3. Validate & populate source attribution across categories
    used_refs: dict[tuple[str, str], str] = {}
    observed_facts = validate_and_attribute_items(
        observed_facts,
        category="observed_facts",
        indexed_findings=indexed_findings,
        evidence_by_id=evidence_by_id,
        used_references=used_refs,
        warnings=warnings,
    )
    analyst_interpretations = validate_and_attribute_items(
        analyst_interpretations,
        category="analyst_interpretations",
        indexed_findings=indexed_findings,
        evidence_by_id=evidence_by_id,
        used_references=used_refs,
        warnings=warnings,
    )
    hypotheses = validate_and_attribute_items(
        hypotheses,
        category="hypotheses",
        indexed_findings=indexed_findings,
        evidence_by_id=evidence_by_id,
        used_references=used_refs,
        warnings=warnings,
    )
    conflicting_findings = validate_and_attribute_items(
        conflicting_findings,
        category="conflicting_findings",
        indexed_findings=indexed_findings,
        evidence_by_id=evidence_by_id,
        used_references=used_refs,
        warnings=warnings,
    )

    # 4. Reconcile missing information against all available evidence & specialist outputs
    existing_report_statements = {
        " ".join(i.statement.casefold().split())
        for group in (
            observed_facts,
            analyst_interpretations,
            hypotheses,
            conflicting_findings,
        )
        for i in group
    }
    reconciled_missing, reconciliation_log = reconcile_missing_information(
        report_input=report_input,
        candidate_missing_items=list(report.missing_information),
        indexed_findings=indexed_findings,
        extracted_values=extracted_values,
        conflicts=conflicting_findings,
        evidence_by_id=evidence_by_id,
        existing_report_statements=existing_report_statements,
    )
    reconciled_missing = validate_and_attribute_items(
        reconciled_missing,
        category="missing_information",
        indexed_findings=indexed_findings,
        evidence_by_id=evidence_by_id,
        used_references=used_refs,
        warnings=warnings,
    )

    # 5. Build deduplicated source inventory & specialist evidence usage registry
    all_report_items = (
        *observed_facts,
        *analyst_interpretations,
        *hypotheses,
        *conflicting_findings,
        *reconciled_missing,
    )
    source_inventory = build_source_inventory(
        report_input=report_input,
        indexed_findings=indexed_findings,
        report_items=list(all_report_items),
    )

    # 6. Cross-agent validation checks
    # Check specialist coverage disclosure
    covered_specialists = {c.specialist: c for c in report.specialist_coverage}
    for spec in CANONICAL_SPECIALISTS:
        actual_status = getattr(report_input, spec).status
        cov = covered_specialists.get(spec)
        if cov is None or cov.status != actual_status:
            failures.append(
                f"Specialist coverage mismatch for {spec}: expected {actual_status}."
            )
        if actual_status in {"unavailable", "failed"}:
            warnings.append(
                f"Specialist '{spec}' execution status is '{actual_status}'; manual human review of its scope is required."
            )

    # Check citation integrity on all items
    for item in all_report_items:
        for eid in item.supporting_evidence_ids:
            if eid not in evidence_by_id:
                failures.append(
                    f"Report item cites unretrieved evidence ID '{eid}'."
                )
        for q in item.supporting_quotes:
            if q.evidence_id not in evidence_by_id or not quote_matches_evidence(
                q.quote, evidence_by_id[q.evidence_id].text
            ):
                failures.append(
                    f"Report quote for evidence ID '{q.evidence_id}' does not match source text."
                )

    policy_ver_status = _compute_policy_verification_status(report_input)
    if policy_ver_status == "pending_review":
        warnings.append(
            "Retrieved policy clauses have verification_status='pending_review' and require human verification."
        )

    # Validate repair estimate calculations and subtotal reconciliation when present
    repair_needs_review = False
    if (
        report_input.repair_estimate_analyst.status
        in {"completed", "insufficient_evidence"}
        and isinstance(report_input.repair_estimate_analyst.analysis, dict)
    ):
        re_data = report_input.repair_estimate_analyst.analysis
        if re_data.get("calculation_complete") is False:
            repair_needs_review = True
        if re_data.get("subtotal_reconciled") is False:
            repair_needs_review = True
            warnings.append(
                "Repair estimate line-item subtotals do not reconcile with printed document totals; human verification is required."
            )
        re_findings = re_data.get("findings")
        if isinstance(re_findings, list):
            for rf in re_findings:
                if isinstance(rf, dict):
                    f_code = str(rf.get("code") or "")
                    f_desc = str(rf.get("description") or "")
                    if f_code in {
                        "invalid_quantity",
                        "reported_amount_mismatch",
                        "subtotal_reconciliation_mismatch",
                        "duplicate_line_items",
                    } and f_desc:
                        repair_needs_review = True
                        warnings.append(f"Repair estimate validation ({f_code}): {f_desc}")

    completeness = _compute_report_completeness(report, report_input)

    has_unverified_attr = any(
        i.attribution_status == "unverified" for i in all_report_items
    )
    if failures:
        validation_status: Literal[
            "validated",
            "validated_with_warnings",
            "flagged_for_human_review",
            "validation_failed",
        ] = "validation_failed"
    elif (
        conflicting_findings
        or has_unverified_attr
        or policy_ver_status == "pending_review"
        or completeness != "complete"
        or repair_needs_review
    ):
        validation_status = "flagged_for_human_review"
    elif warnings:
        validation_status = "validated_with_warnings"
    else:
        validation_status = "validated"

    dedup_warnings = list(dict.fromkeys(warnings))
    dedup_failures = list(dict.fromkeys(failures))

    return report.model_copy(
        update={
            "observed_facts": observed_facts,
            "analyst_interpretations": analyst_interpretations,
            "hypotheses": hypotheses,
            "conflicting_findings": conflicting_findings,
            "missing_information": reconciled_missing,
            "report_completeness": completeness,
            "report_validation_status": validation_status,
            "policy_verification_status": policy_ver_status,
            "source_inventory": source_inventory,
            "missing_information_reconciliation": reconciliation_log,
            "validation_warnings": dedup_warnings,
            "validation_failures": dedup_failures,
            "human_review_required": True,
        }
    )


# ---------------------------------------------------------------------------
# Shared Evidence Context & Pre-Finalization Specialist Reconciliation
# ---------------------------------------------------------------------------


@dataclass
class SharedEvidenceContext:
    """Normalized evidence context shared across Intake, Evidence, Policy, Repair Estimate, and Risk agents."""

    claim_type: str
    evidence_by_id: dict[str, ReviewReportEvidenceChunk] = field(default_factory=dict)
    retrieved_chunks: list[ReviewReportEvidenceChunk] = field(default_factory=list)
    uploaded_documents: list[dict[str, object]] = field(default_factory=list)
    extracted_values: list[ExtractedStructuredValue] = field(default_factory=list)
    document_statuses: dict[str, DocumentEvidenceStatus] = field(default_factory=dict)


def build_shared_evidence_context(
    state: Mapping[str, object],
) -> SharedEvidenceContext:
    """Build one normalized evidence context shared across all specialist agents."""
    claim_facts = state.get("claim_facts")
    claim_type = (
        str(claim_facts.get("claim_type") or "").strip().lower()
        if isinstance(claim_facts, Mapping)
        else ""
    )

    evidence_by_id: dict[str, ReviewReportEvidenceChunk] = {}
    for key in ("claim_evidence", "policy_evidence", "repair_estimate_evidence"):
        raw_list = state.get(key)
        if not isinstance(raw_list, list):
            continue
        for record in raw_list:
            if not isinstance(record, Mapping):
                continue
            try:
                chunk = ReviewReportEvidenceChunk.model_validate(dict(record))
            except Exception:
                continue
            if chunk.chunk_id not in evidence_by_id:
                evidence_by_id[chunk.chunk_id] = chunk

    retrieved_chunks = list(evidence_by_id.values())

    uploaded_docs: list[dict[str, object]] = []
    result = state.get("result")
    if isinstance(result, Mapping):
        raw_up = result.get("uploaded_documents")
        if isinstance(raw_up, list):
            uploaded_docs = [dict(d) for d in raw_up if isinstance(d, Mapping)]

    # Determine canonical document status per document
    doc_statuses: dict[str, DocumentEvidenceStatus] = {}
    chunks_by_fname: dict[str, list[ReviewReportEvidenceChunk]] = {}
    for c in retrieved_chunks:
        chunks_by_fname.setdefault(c.filename.strip().casefold(), []).append(c)

    for fname, c_list in chunks_by_fname.items():
        v_set = {
            str(getattr(c, "verification_status"))
            for c in c_list
            if getattr(c, "verification_status", None) is not None
        }
        if v_set == {"verified"}:
            doc_statuses[fname] = "verified"
        else:
            doc_statuses[fname] = "retrieved_unverified"

    for up in uploaded_docs:
        up_fname = str(up.get("filename") or "").strip().casefold()
        if up_fname and up_fname not in doc_statuses:
            doc_statuses[up_fname] = "uploaded_not_retrieved"

    # Extract structured values from retrieved chunks and claim facts
    extracted = _extract_values_from_chunks(retrieved_chunks, evidence_by_id)

    return SharedEvidenceContext(
        claim_type=claim_type,
        evidence_by_id=evidence_by_id,
        retrieved_chunks=retrieved_chunks,
        uploaded_documents=uploaded_docs,
        extracted_values=extracted,
        document_statuses=doc_statuses,
    )


def _check_missing_statement_satisfied(
    statement: str,
    orig_spec: str,
    ctx: SharedEvidenceContext,
    state: Mapping[str, object],
) -> MissingInformationReconciliationItem | None:
    """Return a reconciliation item if ``statement`` is already satisfied by the shared context
    or is not applicable to the claim domain; otherwise return None.
    """
    combined_lower = statement.casefold()
    claim_type = ctx.claim_type
    is_health = claim_type == "health"
    is_motor = claim_type in {"auto", "motor"}

    # 1. Domain applicability check
    if is_health and any(kw in combined_lower for kw in _MOTOR_ONLY_KEYWORDS):
        return MissingInformationReconciliationItem(
            field_or_topic=statement[:120],
            original_statement=statement,
            originating_specialist=orig_spec,
            reconciled_category="not_applicable",
            retained_in_missing_information=False,
            reconciliation_note=(
                "Motor/vehicle-specific requirement is not applicable to a health claim."
            ),
        )
    if is_motor and any(kw in combined_lower for kw in _HEALTH_ONLY_KEYWORDS):
        return MissingInformationReconciliationItem(
            field_or_topic=statement[:120],
            original_statement=statement,
            originating_specialist=orig_spec,
            reconciled_category="not_applicable",
            retained_in_missing_information=False,
            reconciliation_note=(
                "Hospital/inpatient-specific requirement is not applicable to a motor claim."
            ),
        )

    # 2. Policy evidence check
    policy_chunks = [
        ev
        for ev in ctx.retrieved_chunks
        if getattr(ev, "clause_identifier", None) is not None
        or "policy" in ev.filename.lower()
    ]
    is_policy_missing_claim = any(
        phrase in combined_lower
        for phrase in (
            "policy document",
            "policy schedule",
            "policy wording",
            "policy terms",
            "policy coverage",
            "policy copy",
            "policy clauses",
        )
    )
    if is_policy_missing_claim and policy_chunks:
        pol_filenames = sorted({ev.filename for ev in policy_chunks})
        pol_ev_ids = [ev.chunk_id for ev in policy_chunks]
        return MissingInformationReconciliationItem(
            field_or_topic="Policy Schedule / Clauses",
            original_statement=statement,
            originating_specialist=orig_spec,
            reconciled_category="retrieved_unverified",
            available_in_sources=pol_filenames,
            supporting_evidence_ids=pol_ev_ids,
            retained_in_missing_information=False,
            reconciliation_note=(
                f"Policy evidence was retrieved from {', '.join(pol_filenames)}; "
                "classified as retrieved_unverified rather than absent."
            ),
        )

    # 3. Topic matchers against all retrieved chunks in shared context
    matched_topic_label: str | None = None
    matched_chunks: list[ReviewReportEvidenceChunk] = []
    for topic_label, trigger_phrases, evidence_markers in _TOPIC_EVIDENCE_MATCHERS:
        if any(tp in combined_lower for tp in trigger_phrases):
            for ev in ctx.retrieved_chunks:
                ev_haystack = f"{ev.filename} {ev.text}".casefold()
                if any(em in ev_haystack for em in evidence_markers):
                    matched_chunks.append(ev)
            if matched_chunks:
                matched_topic_label = topic_label
                break

    # 4. Check specialist-specific repair estimate retrieval / output
    if (
        not matched_chunks
        and "repair estimate" in combined_lower
        and (
            bool(state.get("repair_estimate_evidence"))
            or (
                state.get("repair_estimate_analysis_status") == "completed"
                and isinstance(state.get("repair_estimate_analysis"), Mapping)
            )
        )
    ):
        matched_topic_label = "Repair Estimate"
        matched_chunks = [
            ev
            for ev in ctx.retrieved_chunks
            if "estimate" in ev.filename.lower() or "repair" in ev.text.lower()
        ]

    # 5. Check extracted structured values
    if not matched_chunks:
        for ev_val in ctx.extracted_values:
            if not ev_val.is_partial and ev_val.evidence_id in ctx.evidence_by_id:
                role_words = ev_val.role.replace("_", " ")
                if (
                    role_words in combined_lower
                    or ev_val.label.casefold() in combined_lower
                ):
                    matched_topic_label = ev_val.label
                    matched_chunks = [ctx.evidence_by_id[ev_val.evidence_id]]
                    break

    if matched_topic_label is not None and matched_chunks:
        src_files = sorted({c.filename for c in matched_chunks})
        src_ev_ids = [c.chunk_id for c in matched_chunks]
        return MissingInformationReconciliationItem(
            field_or_topic=matched_topic_label,
            original_statement=statement,
            originating_specialist=orig_spec,
            reconciled_category="retrieved_unverified",
            available_in_sources=src_files,
            supporting_evidence_ids=src_ev_ids,
            retained_in_missing_information=False,
            reconciliation_note=(
                f"Reconciled against shared evidence context in {', '.join(src_files)}; "
                "removed from specialist missing_information before finalization."
            ),
        )

    return None


def reconcile_specialist_missing_in_state(
    state: Mapping[str, object],
) -> dict[str, object]:
    """Reconcile all completed specialists' missing_information against the shared
    evidence context before any agent's missing-information findings are finalized.

    Only mutates a specialist dict when at least one false-positive missing item
    is reconciled out, preserving exact object identity when unchanged.
    """
    ctx = build_shared_evidence_context(state)
    spec_mapping = (
        ("intake_analysis", "intake_agent"),
        ("evidence_analysis", "evidence_analyst"),
        ("policy_analysis", "policy_analyst"),
        ("repair_estimate_analysis", "repair_estimate_analyst"),
        ("risk_analysis", "risk_anomaly_agent"),
    )

    state_updates: dict[str, object] = {}
    reconciled_records: list[dict[str, object]] = []
    result = state.get("result")
    existing_reconciled: list[dict[str, object]] = []
    if isinstance(result, Mapping) and isinstance(
        result.get("shared_evidence_reconciliation"), list
    ):
        existing_reconciled = [
            dict(r)
            for r in result["shared_evidence_reconciliation"]
            if isinstance(r, Mapping)
        ]
    seen_norms = {
        " ".join(str(r.get("original_statement") or "").casefold().split())
        for r in existing_reconciled
    }

    for state_key, spec_name in spec_mapping:
        analysis = state.get(state_key)
        if not isinstance(analysis, Mapping):
            continue
        raw_missing = analysis.get("missing_information")
        if not isinstance(raw_missing, list) or not raw_missing:
            continue

        new_missing: list[object] = []
        changed = False
        for item in raw_missing:
            if isinstance(item, str):
                stmt = item.strip()
            elif isinstance(item, Mapping):
                stmt = str(item.get("finding") or item.get("statement") or "").strip()
            else:
                new_missing.append(item)
                continue

            if not stmt:
                continue

            rec = _check_missing_statement_satisfied(stmt, spec_name, ctx, state)
            if rec is not None:
                changed = True
                norm = " ".join(stmt.casefold().split())
                if norm not in seen_norms:
                    seen_norms.add(norm)
                    reconciled_records.append(rec.model_dump(mode="json"))
            else:
                new_missing.append(item)

        if changed:
            updated_analysis = {**dict(analysis), "missing_information": new_missing}
            state_updates[state_key] = updated_analysis

    if state_updates or reconciled_records:
        all_reconciled = [*existing_reconciled, *reconciled_records]
        if isinstance(result, Mapping):
            updated_result = {
                **dict(result),
                **state_updates,
                "shared_evidence_reconciliation": all_reconciled,
                "shared_document_statuses": dict(ctx.document_statuses),
            }
            state_updates["result"] = updated_result

    return state_updates
