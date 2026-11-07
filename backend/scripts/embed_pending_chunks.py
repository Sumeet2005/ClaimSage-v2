"""Generate and persist embeddings for pending ClaimSage policy chunks."""

import argparse
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from claimsage.db.models import PolicyChunk
from claimsage.db.session import SessionLocal
from claimsage.services.embedding_persistence import (
    embed_pending_policy_chunks,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-id",
        type=UUID,
        help="Embed pending chunks from this policy document only.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    with SessionLocal() as db:
        try:
            processed = embed_pending_policy_chunks(
                db=db,
                batch_size=10,
                document_id=args.document_id,
            )
            pending_query = select(PolicyChunk.id).where(
                PolicyChunk.embedding.is_(None)
            )
            if args.document_id is not None:
                pending_query = pending_query.where(
                    PolicyChunk.document_id == args.document_id
                )
            more_pending = db.scalar(pending_query.limit(1)) is not None
            db.commit()
            scope = (
                f"for document {args.document_id}"
                if args.document_id is not None
                else "from the global pending queue"
            )
            print(f"Embedded {processed} policy chunks {scope}.")
            print(
                "More pending chunks may remain: "
                f"{'yes' if more_pending else 'no'}."
            )
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    main()
