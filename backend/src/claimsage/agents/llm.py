"""Groq-backed language model provider for ClaimSage agents."""

from functools import lru_cache

from langchain_groq import ChatGroq

from claimsage.core.config import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatGroq:
    """Create and cache the configured Groq chat model."""
    settings = get_settings()

    if settings.groq_api_key is None:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to the backend environment."
        )

    api_key = settings.groq_api_key.get_secret_value().strip()

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is empty.")

    return ChatGroq(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        api_key=api_key,
    )
