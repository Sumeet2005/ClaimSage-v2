"""Centralized configurable token-budget manager for ClaimSage agents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import tiktoken
from pydantic import BaseModel

from claimsage.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default per-agent maximum input token budgets to guarantee compliance
# with provider rate limits (e.g. Groq 8,000 TPM limit over rolling 60s).
DEFAULT_AGENT_BUDGETS: dict[str, int] = {
    "supervisor": 1200,
    "intake_agent": 3400,
    "evidence_analyst": 3400,
    "policy_analyst": 4400,
    "risk_anomaly_agent": 3600,
    "repair_estimate_analyst": 3400,
    "review_report": 3800,
}

DEFAULT_SAFETY_MARGIN_RATIO = 0.10  # 10% safety margin
DEFAULT_RESERVED_OUTPUT_TOKENS = 1024


@dataclass(frozen=True, slots=True)
class TokenBudgetAllocation:
    """Token budget configuration for a specific agent stage."""

    stage: str
    max_input_tokens: int
    reserved_output_tokens: int
    safety_margin_ratio: float

    @property
    def effective_input_budget(self) -> int:
        """Maximum tokens available for prompts after safety margin."""
        margin = int(self.max_input_tokens * self.safety_margin_ratio)
        return max(200, self.max_input_tokens - margin)


@dataclass(slots=True)
class TokenBudgetUsage:
    """Safe diagnostic metadata recorded for each specialist invocation."""

    stage: str
    model: str
    provider: str
    prompt_tokens: int
    schema_tokens: int
    total_estimated_tokens: int
    budget_limit: int
    candidate_passages: int = 0
    selected_passages: int = 0
    omitted_passages: int = 0
    deduplicated_passages: int = 0
    safety_margin_tokens: int = 0
    actual_provider_tokens: int | None = None
    execution_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return safe diagnostic metadata without PII or credentials."""
        return {
            "stage": self.stage,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "schema_tokens": self.schema_tokens,
            "total_estimated_tokens": self.total_estimated_tokens,
            "budget_limit": self.budget_limit,
            "candidate_passages": self.candidate_passages,
            "selected_passages": self.selected_passages,
            "omitted_passages": self.omitted_passages,
            "deduplicated_passages": self.deduplicated_passages,
            "safety_margin_tokens": self.safety_margin_tokens,
            "actual_provider_tokens": self.actual_provider_tokens,
            "execution_duration_seconds": round(self.execution_duration_seconds, 3),
        }


class TokenBudgetManager:
    """Manages token counting, budgets, and passage prioritization."""

    def __init__(
        self,
        *,
        budgets: dict[str, int] | None = None,
        reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS,
        safety_margin_ratio: float = DEFAULT_SAFETY_MARGIN_RATIO,
    ) -> None:
        self.budgets = dict(DEFAULT_AGENT_BUDGETS)
        if budgets:
            self.budgets.update(budgets)
        self.reserved_output_tokens = reserved_output_tokens
        self.safety_margin_ratio = safety_margin_ratio
        self._encoding: Any = None

    def _get_encoding(self) -> Any:
        if self._encoding is None:
            settings = get_settings()
            encoding_name = getattr(
                settings, "groq_tokenizer_encoding", "o200k_harmony"
            )
            try:
                self._encoding = tiktoken.get_encoding(encoding_name)
            except Exception:
                try:
                    self._encoding = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    self._encoding = None
        return self._encoding

    def count_text_tokens(self, text: str) -> int:
        """Estimate token count for a text string using tokenizer or word fallback."""
        if not text:
            return 0
        encoding = self._get_encoding()
        if encoding is not None:
            try:
                return len(encoding.encode(text, disallowed_special=()))
            except Exception:
                pass
        # Fallback heuristic: 1 token ≈ 4 characters or 0.75 words
        return max(1, int(len(text.split()) * 1.33))

    def count_request_tokens(
        self,
        *,
        messages: list[tuple[str, str]],
        output_schema: type[BaseModel] | None = None,
    ) -> tuple[int, int, int]:
        """Count prompt tokens, schema tokens, and total estimated bytes."""
        message_text = "\n".join(
            f"{role}\n{content}" for role, content in messages
        )
        prompt_tokens = self.count_text_tokens(message_text)

        schema_tokens = 0
        schema_bytes = 0
        if output_schema is not None:
            try:
                schema_dict = output_schema.model_json_schema()
                schema_json = json.dumps(
                    schema_dict,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                schema_tokens = self.count_text_tokens(schema_json)
                schema_bytes = len(schema_json.encode("utf-8"))
            except Exception:
                pass

        total_bytes = len(message_text.encode("utf-8")) + schema_bytes
        return prompt_tokens, schema_tokens, total_bytes

    def get_allocation(self, stage: str) -> TokenBudgetAllocation:
        """Return the token budget allocation for a given stage."""
        budget = self.budgets.get(stage, 2500)
        return TokenBudgetAllocation(
            stage=stage,
            max_input_tokens=budget,
            reserved_output_tokens=self.reserved_output_tokens,
            safety_margin_ratio=self.safety_margin_ratio,
        )

    def fit_passages_to_budget(
        self,
        passages: list[T],
        *,
        stage: str,
        base_prompt_tokens: int,
        schema_tokens: int = 0,
        text_accessor: Callable[[T], str] = lambda p: getattr(p, "text", str(p)),
        id_accessor: Callable[[T], str] = lambda p: getattr(p, "chunk_id", str(id(p))),
        mandatory_predicate: Callable[[T], bool] = lambda p: bool(getattr(p, "is_mandatory", False)),
        score_accessor: Callable[[T], float] = lambda p: float(getattr(p, "relevance_score", 0.0) or 0.0),
    ) -> tuple[list[T], list[T], dict[str, Any]]:
        """Fit candidate passages within the stage's token budget.

        Prioritizes mandatory passages first, then ranks remaining candidates
        by relevance score descending. Redundant passages are omitted if budget
        is exceeded.
        """
        allocation = self.get_allocation(stage)
        effective_budget = allocation.effective_input_budget

        available_tokens = effective_budget - (base_prompt_tokens + schema_tokens)
        if available_tokens <= 0:
            logger.warning(
                "Base prompt and schema already exceed effective budget for %s (base=%d, schema=%d, budget=%d)",
                stage,
                base_prompt_tokens,
                schema_tokens,
                effective_budget,
            )
            # Allow at least a minimum token allocation for essential passages
            available_tokens = max(300, allocation.max_input_tokens - (base_prompt_tokens + schema_tokens))

        selected: list[T] = []
        omitted: list[T] = []
        used_passage_tokens = 0

        # Separate mandatory vs standard candidate passages
        mandatory: list[T] = []
        standard: list[T] = []
        for p in passages:
            if mandatory_predicate(p):
                mandatory.append(p)
            else:
                standard.append(p)

        # 1. Allocate mandatory passages first
        for p in mandatory:
            p_text = text_accessor(p)
            p_tokens = self.count_text_tokens(p_text)
            selected.append(p)
            used_passage_tokens += p_tokens

        # 2. Sort standard candidates by relevance score descending
        standard.sort(key=score_accessor, reverse=True)

        for p in standard:
            p_text = text_accessor(p)
            p_tokens = self.count_text_tokens(p_text)
            if used_passage_tokens + p_tokens <= available_tokens or not selected:
                selected.append(p)
                used_passage_tokens += p_tokens
            else:
                omitted.append(p)

        stats = {
            "stage": stage,
            "budget_limit": allocation.max_input_tokens,
            "effective_budget": effective_budget,
            "base_prompt_tokens": base_prompt_tokens,
            "schema_tokens": schema_tokens,
            "passage_tokens": used_passage_tokens,
            "total_estimated_tokens": base_prompt_tokens + schema_tokens + used_passage_tokens,
            "candidate_count": len(passages),
            "selected_count": len(selected),
            "omitted_count": len(omitted),
            "safety_margin_tokens": int(allocation.max_input_tokens * allocation.safety_margin_ratio),
        }
        return selected, omitted, stats


# Global singleton instance
_budget_manager: TokenBudgetManager | None = None


def get_token_budget_manager() -> TokenBudgetManager:
    """Return the global TokenBudgetManager instance."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = TokenBudgetManager()
    return _budget_manager
