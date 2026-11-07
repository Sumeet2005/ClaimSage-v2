"""Send one minimal, non-claim Groq request using process credentials only."""

from __future__ import annotations

import os
import re
import sys

from groq import APIStatusError, Groq

os.environ["CLAIMSAGE_DISABLE_DOTENV"] = "1"

_SAFE_PROVIDER_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_EXPECTED_RESPONSE = "CLAIMSAGE_GROQ_SMOKE_OK"


def main() -> int:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("GROQ_SMOKE=BLOCKED (process GROQ_API_KEY is unset)")
        return 2

    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    client = Groq(
        api_key=api_key,
        timeout=20.0,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Reply with exactly CLAIMSAGE_GROQ_SMOKE_OK "
                        "and no other text."
                    ),
                },
                {"role": "user", "content": "Confirm the smoke test."},
            ],
            temperature=0,
            max_tokens=128,
        )
    except APIStatusError as error:
        code = getattr(error, "code", None)
        safe_code = (
            code
            if isinstance(code, str) and _SAFE_PROVIDER_CODE.fullmatch(code)
            else "unavailable"
        )
        print(
            "GROQ_SMOKE=FAIL "
            f"(status={error.status_code}, provider_code={safe_code})"
        )
        return 1
    except Exception as error:
        print(f"GROQ_SMOKE=FAIL (error_type={type(error).__name__})")
        return 1

    content = response.choices[0].message.content
    if content != _EXPECTED_RESPONSE:
        print("GROQ_SMOKE=FAIL (response_validation=failed)")
        return 1
    print("GROQ_SMOKE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
