"""Semantic retrieval for ClaimSage policy documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from claimsage.db.models import (
    Claim,
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentApplicability,
)
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    get_embedding_service,
)
from claimsage.schemas.policies import normalize_insurance_type
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.document_access import (
    PolicyDocumentAccessDeniedError,
    build_policy_document_access_filter,
)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MIN_SIMILARITY = 0.0


class PolicyRetrievalError(RuntimeError):
    """Raised when policy semantic retrieval fails."""


@dataclass(frozen=True, slots=True)
class RetrievedPolicyChunk:
    """A policy chunk returned by semantic similarity search."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str
    similarity: float
    embedding_model: str
    clause_id: UUID | None
    clause_identifier: str | None
    clause_category: str | None
    verification_status: str | None
    policy_version: str | None
    source_url: str | None = None
    insurer_name: str | None = None
    product_name: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


def _normalized_claim_type(claim_type: str) -> str:
    if not isinstance(claim_type, str) or not claim_type.strip():
        raise ValueError("claim_type must not be empty.")
    return normalize_insurance_type(claim_type)


def _applicable_policy_document_ids(
    db: Session,
    *,
    claim: Claim,
    normalized_type: str,
    document_access_filter: ColumnElement[bool],
) -> list[UUID]:
    """Resolve accessible source documents for one unambiguous loss-date version."""

    if (
        not isinstance(claim.policy_identifier, str)
        or not claim.policy_identifier.strip()
        or claim.loss_date is None
    ):
        return []

    health_metadata_filters = []
    if normalized_type == "health":
        insurer_name = getattr(claim, "insurer_name", None)
        product_name = getattr(claim, "product_name", None)
        if (
            not isinstance(insurer_name, str)
            or not insurer_name.strip()
            or not isinstance(product_name, str)
            or not product_name.strip()
        ):
            return []
        health_metadata_filters = [
            func.lower(func.trim(PolicyDocument.insurer_name))
            == insurer_name.strip().lower(),
            func.lower(func.trim(PolicyDocument.product_name))
            == product_name.strip().lower(),
        ]

    statement = (
        select(
            PolicyDocument.id,
            PolicyDocument.policy_version,
            PolicyDocument.effective_from,
            PolicyDocument.effective_to,
        )
        .join(
            PolicyDocumentApplicability,
            PolicyDocumentApplicability.document_id == PolicyDocument.id,
        )
        .where(
            PolicyDocument.status == "processed",
            PolicyDocument.policy_identifier
            == claim.policy_identifier.strip(),
            PolicyDocument.insurance_type == normalized_type,
            PolicyDocument.policy_version.is_not(None),
            PolicyDocument.effective_from.is_not(None),
            PolicyDocument.effective_from <= claim.loss_date,
            (
                PolicyDocument.effective_to.is_(None)
                | (PolicyDocument.effective_to >= claim.loss_date)
            ),
            PolicyDocumentApplicability.claim_type == normalized_type,
            document_access_filter,
            *health_metadata_filters,
        )
        .order_by(
            PolicyDocument.effective_from.desc(),
            PolicyDocument.policy_version.asc(),
            PolicyDocument.id.asc(),
        )
    )
    rows = db.execute(statement).all()
    versions = {
        (policy_version, effective_from, effective_to)
        for _, policy_version, effective_from, effective_to in rows
    }
    if len(versions) != 1:
        return []
    return [document_id for document_id, *_ in rows]


def has_applicable_policy_documents(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
) -> bool:
    """Check for a processed, authorized policy with exact applicability."""

    if not isinstance(employee_id, UUID):
        raise ValueError("employee_id must be a UUID.")
    if not isinstance(claim_id, UUID):
        raise ValueError("claim_id must be a UUID.")

    claim = get_authorized_claim(
        db,
        employee_id=employee_id,
        claim_id=claim_id,
    )
    normalized_type = _normalized_claim_type(claim.claim_type)
    document_access_filter = build_policy_document_access_filter(
        db,
        employee_id=employee_id,
        claim_id=claim_id,
    )
    try:
        applicable_documents = _applicable_policy_document_ids(
            db,
            claim=claim,
            normalized_type=normalized_type,
            document_access_filter=document_access_filter,
        )
        return bool(applicable_documents)
    except Exception as exc:
        raise PolicyRetrievalError(
            "Policy applicability lookup failed."
        ) from exc


def search_policy_chunks(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[RetrievedPolicyChunk]:
    """Retrieve relevant chunks only from documents the employee may access.

    Claim authorization and document authorization are enforced before
    generating embeddings or retrieving policy text.

    Similarity filtering is applied in SQL before ordering and limiting
    results, ensuring qualifying chunks are not unnecessarily excluded.
    """

    if not isinstance(employee_id, UUID):
        raise ValueError("employee_id must be a UUID.")

    if not isinstance(claim_id, UUID):
        raise ValueError("claim_id must be a UUID.")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty.")

    if (
        not isinstance(top_k, int)
        or isinstance(top_k, bool)
        or not 1 <= top_k <= MAX_TOP_K
    ):
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}.")

    if (
        not isinstance(min_similarity, (int, float))
        or isinstance(min_similarity, bool)
        or not 0.0 <= min_similarity <= 1.0
    ):
        raise ValueError("min_similarity must be between 0 and 1.")
    try:
        claim = get_authorized_claim(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )
        normalized_type = _normalized_claim_type(claim.claim_type)

        # Authorization must happen before embedding generation.
        document_access_filter = build_policy_document_access_filter(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )

        applicable_document_ids = _applicable_policy_document_ids(
            db,
            claim=claim,
            normalized_type=normalized_type,
            document_access_filter=document_access_filter,
        )
        if not applicable_document_ids:
            return []

        embedding_service = get_embedding_service()
        query_vector = embedding_service.embed_query(query.strip())

        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise PolicyRetrievalError(
                "Query embedding has an unexpected dimension."
            )

        cosine_distance = PolicyChunk.embedding.cosine_distance(
            query_vector
        ).label("cosine_distance")

        # Cosine similarity = 1 - cosine distance.
        # Apply the minimum similarity threshold inside SQL.
        maximum_distance = 1.0 - float(min_similarity)

        statement = (
            select(
                PolicyChunk,
                PolicyDocument.filename,
                PolicyDocument.source_url,
                PolicyDocument.insurer_name,
                PolicyDocument.product_name,
                cosine_distance,
                PolicyDocument.policy_version,
                PolicyDocument.effective_from,
                PolicyDocument.effective_to,
                PolicyClause.id,
                PolicyClause.clause_identifier,
                PolicyClause.clause_category,
                PolicyClause.verification_status,
                PolicyClause.clause_text,
            )
            .join(
                PolicyDocument,
                PolicyDocument.id == PolicyChunk.document_id,
            )
            .join(
                PolicyDocumentApplicability,
                PolicyDocumentApplicability.document_id == PolicyDocument.id,
            )
            .outerjoin(
                PolicyClause,
                PolicyClause.source_chunk_id == PolicyChunk.id,
            )
            .where(
                PolicyDocument.status == "processed",
                PolicyDocument.policy_identifier
                == claim.policy_identifier.strip(),
                PolicyDocumentApplicability.claim_type == normalized_type,
                PolicyDocument.id.in_(applicable_document_ids),
                PolicyChunk.embedding.is_not(None),
                PolicyChunk.embedding_model == embedding_service.model_name,
                document_access_filter,
                cosine_distance <= maximum_distance,
            )
            .order_by(
                cosine_distance.asc(),
                PolicyChunk.id.asc(),
            )
            .limit(top_k)
        )

        rows = db.execute(statement).all()

        results: list[RetrievedPolicyChunk] = []

        for (
            chunk,
            filename,
            source_url,
            insurer_name,
            product_name,
            distance,
            policy_version,
            effective_from,
            effective_to,
            clause_id,
            clause_identifier,
            clause_category,
            verification_status,
            clause_text,
        ) in rows:
            similarity = max(
                0.0,
                min(1.0, 1.0 - float(distance)),
            )

            results.append(
                RetrievedPolicyChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=clause_text if clause_text is not None else chunk.text,
                    similarity=similarity,
                    embedding_model=chunk.embedding_model,
                    clause_id=clause_id,
                    clause_identifier=clause_identifier,
                    clause_category=clause_category,
                    verification_status=verification_status,
                    policy_version=policy_version,
                    source_url=source_url,
                    insurer_name=insurer_name,
                    product_name=product_name,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
            )

        return results

    except (
        ClaimAccessDeniedError,
        PolicyDocumentAccessDeniedError,
    ):
        raise

    except PolicyRetrievalError:
        raise

    except Exception as exc:
        raise PolicyRetrievalError(
            "Policy semantic retrieval failed."
        ) from exc
