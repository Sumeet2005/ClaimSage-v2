"""Test semantic retrieval against persisted ClaimSage policy chunks."""

# Explicitly instruct pytest not to collect this manual CLI script as a test.
__test__ = False

import argparse
from uuid import UUID

from claimsage.db.session import SessionLocal
from claimsage.rag.retrieval_service import search_policy_chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--employee-id", type=UUID, required=True)
    parser.add_argument("--claim-id", type=UUID, required=True)
    args = parser.parse_args()

    queries = [
        "What is the waiting period for hospitalization?",
        "How many days of medical expenses before hospitalization are covered?",
        "What is the maximum room rent per day?",
    ]

    with SessionLocal() as db:
        for query in queries:
            print("\n" + "=" * 80)
            print(f"QUESTION: {query}")
            print("=" * 80)

            results = search_policy_chunks(
                db,
                employee_id=args.employee_id,
                claim_id=args.claim_id,
                query=query,
                top_k=3,
            )

            if not results:
                print("No relevant policy chunks found.")
                continue

            for index, result in enumerate(results, start=1):
                print(f"\nResult {index}")
                print(f"Filename: {result.filename}")
                print(f"Page: {result.page_number}")
                print(f"Chunk: {result.chunk_index}")
                print(f"Similarity: {result.similarity:.4f}")
                print(f"Text: {result.text}")


if __name__ == "__main__":
    main()
