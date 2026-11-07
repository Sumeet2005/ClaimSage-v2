"""Execute Phase 2: Real Provider Smoke Test.

Sends exactly one minimal, non-claim-related structured request through
invoke_structured() and verifies connectivity, schema output, rate coordination,
and invocation token diagnostics without exposing any credentials.
"""

from __future__ import annotations

import json
import logging
import sys
from pydantic import BaseModel

from claimsage.core.config import get_settings
from claimsage.agents.llm import (
    get_chat_model,
    invoke_structured,
    get_last_invocation_diagnostic,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SmokeTestOutput(BaseModel):
    status: str
    confirmation: str


def run_smoke_test() -> int:
    settings = get_settings()

    if not settings.groq_api_key or not settings.groq_api_key.get_secret_value().strip():
        print("PHASE2_SMOKE=FAILED (GROQ_API_KEY is not configured in environment)")
        return 1

    print(f"Provider: Groq | Configured Model: {settings.groq_model}")
    print("Initiating single minimal structured test request via invoke_structured()...")

    model = get_chat_model()
    structured_model = model.with_structured_output(
        SmokeTestOutput,
        method="function_calling",
    )

    messages = [
        (
            "system",
            "You are an automated connectivity verification agent. "
            "Respond in JSON matching the requested schema with status 'verified' "
            "and confirmation 'CLAIMSAGE_READY'.",
        ),
        ("human", "Verify system connectivity and structured JSON output."),
    ]

    try:
        result: SmokeTestOutput = invoke_structured(
            structured_model,
            messages=messages,
            output_schema=SmokeTestOutput,
            stage="supervisor",
        )
    except Exception as exc:
        print(f"PHASE2_SMOKE=FAILED (exception={type(exc).__name__}: {exc})")
        return 1

    diag = get_last_invocation_diagnostic()

    print("\n--- Smoke Test Verification Results ---")
    print(f"Structured Output: status='{result.status}', confirmation='{result.confirmation}'")
    print(f"Invocation Diagnostic Status: {diag.get('status') if diag else None}")
    print(f"Estimated Input Tokens: {diag.get('estimated_input_tokens') if diag else None}")
    print(f"Actual Prompt Tokens: {diag.get('actual_prompt_tokens') if diag else None}")
    print(f"Actual Completion Tokens: {diag.get('actual_completion_tokens') if diag else None}")
    print(f"Execution Duration: {diag.get('execution_duration') if diag else None}s")
    print(f"Retry Attempts: {diag.get('retry_attempts') if diag else 0}")

    if not (result.status.casefold() in {"verified", "ok", "success"} and "ready" in result.confirmation.casefold()):
        print(f"PHASE2_SMOKE=FAILED (unexpected output values: {result})")
        return 1

    if not diag or diag.get("status") != "completed":
        print("PHASE2_SMOKE=FAILED (invocation diagnostic did not record completion)")
        return 1

    print("\nPHASE2_SMOKE=PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run_smoke_test())
