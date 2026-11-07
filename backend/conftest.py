"""Backend-wide pytest plugin registration."""

import os

if not os.environ.get("JWT_SECRET_KEY") or len(os.environ.get("JWT_SECRET_KEY", "")) < 32:
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-that-is-at-least-32-bytes-long"
if not os.environ.get("APP_ENV"):
    os.environ["APP_ENV"] = "test"

pytest_plugins = ("tests.test_claim_access",)
