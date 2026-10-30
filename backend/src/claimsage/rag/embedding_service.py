
"""Local embedding service for ClaimSage policy retrieval."""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_DEVICE = "cpu"
MAX_BATCH_SIZE = 64


class EmbeddingServiceError(RuntimeError):
    """Raised when local embedding generation fails."""


class LocalEmbeddingService:
    """Generate normalized embeddings using a local Sentence Transformer."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        device: str = EMBEDDING_DEVICE,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        """Load the model only when the first embedding is requested."""

        if self._model is None:
            try:
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                )
            except Exception as exc:
                raise EmbeddingServiceError(
                    "The local embedding model could not be loaded."
                ) from exc

            if self._model.get_embedding_dimension() != EMBEDDING_DIMENSIONS:
                self._model = None
                raise EmbeddingServiceError(
                    f"The embedding model must produce {EMBEDDING_DIMENSIONS}-"
                    "dimensional vectors."
                )

        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized embeddings for a batch of text inputs."""

        if not isinstance(texts, list) or not texts:
            raise ValueError("At least one text input is required.")

        if len(texts) > MAX_BATCH_SIZE:
            raise ValueError(
                f"A maximum of {MAX_BATCH_SIZE} texts can be embedded per batch."
            )

        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("All embedding inputs must be non-empty strings.")

        model = self._load_model()

        try:
            embeddings = model.encode(
                texts,
                batch_size=MAX_BATCH_SIZE,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbeddingServiceError(
                "Local embedding generation failed."
            ) from exc

        if embeddings.shape != (len(texts), EMBEDDING_DIMENSIONS):
            raise EmbeddingServiceError(
                "The embedding model returned an unexpected vector shape."
            )

        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Generate one normalized embedding for a search query."""

        if not isinstance(query, str) or not query.strip():
            raise ValueError("The search query must not be empty.")

        return self.embed_texts([query.strip()])[0]


@lru_cache(maxsize=1)
def get_embedding_service() -> LocalEmbeddingService:
    """Return the shared embedding service instance."""

    return LocalEmbeddingService()
