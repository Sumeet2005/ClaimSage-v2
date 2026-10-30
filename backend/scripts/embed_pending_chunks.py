"""Generate and persist embeddings for pending ClaimSage policy chunks."""

from claimsage.db.session import SessionLocal
from claimsage.services.embedding_persistence import (
    embed_pending_policy_chunks,
)


def main() -> None:
    with SessionLocal() as db:
        try:
            processed = embed_pending_policy_chunks(
                db=db,
                batch_size=10,
            )
            db.commit()
            print(f"Successfully embedded {processed} policy chunks.")
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    main()
