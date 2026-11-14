# ClaimSage — Testing Guide & Verification Standards

ClaimSage enforces strict testing standards to guarantee zero data corruption, reliable mock isolation, and deterministic validation across all AI agent workflows.

---

## 1. Test Database Isolation

Automated tests **never** execute against the live development or production database (`claimsage`). The test configuration strictly enforces:
- `APP_ENV=test`
- `DATABASE_URL` must explicitly target `claimsage_test`.
- The session start hook (`backend/tests/conftest.py`) validates `parsed_url.database == "claimsage_test"` before running any test.
- An in-memory object storage fixture isolates file operations from persistent MinIO buckets.

---

## 2. Test Execution Commands

### A. Run the Complete Backend Test Suite
```powershell
$env:CLAIMSAGE_DISABLE_DOTENV="1"
$env:APP_ENV="test"
$env:DATABASE_URL="postgresql+psycopg://claimsage_app:change-this-local-password@127.0.0.1:5432/claimsage_test"
$env:JWT_SECRET_KEY="test-secret-key-at-least-32-chars-long-for-pytest"
$env:GROQ_API_KEY="gsk_test_dummy_key_for_unit_tests_only"
.\.venv\Scripts\pytest.exe backend/tests -q
```
**Latest Verified Result**: `814 passed, 0 failed, 0 skipped in 23375.36s` (full suite), and `52 passed, 0 failed in 22.92s` (targeted acceptance suite).

### B. Run Fast Targeted Subsuites
```powershell
# Configuration & validation tests
.\.venv\Scripts\pytest.exe backend/tests/test_config.py backend/tests/test_config_validation.py -q
# Expected: 28 passed in ~0.2s

# LLM provider & fallback tests
.\.venv\Scripts\pytest.exe backend/tests/test_llm.py -q
# Expected: 28 passed in ~1.3s

# Reliability & remediation tests
.\.venv\Scripts\pytest.exe backend/tests/test_reliability_remediation.py -q
# Expected: 19 passed in ~1.0s
```

### C. Run Frontend Typecheck and Production Build
From the `frontend` directory:
```powershell
cd frontend
npm run typecheck
npm run build
```
**Latest Verified Result**:
- `tsc -b`: 0 errors
- `vite build`: Production bundle compiled cleanly in `1.00s`.

---

## 3. Mocked vs Live Provider Testing

- **Mocked Provider Tests**: Tests in `test_llm.py`, `test_agent_graph.py`, and `test_review_report_agent.py` simulate LLM responses, HTTP 429 rate limits, and fallback failovers using synthetic test fixtures. **No real API credits or tokens are consumed.**
- **Live Provider Testing**: Requires valid cloud credentials (`GROQ_API_KEY`, `GEMINI_API_KEY`) and is executed only through controlled smoke scripts (`scripts/groq_smoke_test.py`). Live cloud tests are never run during CI or automated test suites.

---

## 4. Live Service Verification Procedures

To verify that the live Docker infrastructure is operational:

### 1. Check Container Health
```powershell
docker compose -p claimsage ps
```
All five containers (`claimsage-db`, `claimsage-minio`, `claimsage-backend`, `claimsage-worker`, `claimsage-frontend`) should display `Up (healthy)`.

### 2. Verify Health and Readiness Endpoints
```powershell
Invoke-RestMethod -Uri "http://localhost:8080/health/ready" -Method Get
```
Expected output:
```json
{
  "status": "ready",
  "service": "claimsage-api",
  "database": "connected",
  "queue": "ready",
  "storage": "connected"
}
```

### 3. Verify Reference Investigation & Claim Preservation
```powershell
docker exec claimsage-db psql -U claimsage_app -d claimsage -c "SELECT claim_number, claimant_name, status FROM claims WHERE claim_number = 'CLM-DEMO-HEALTH-001';"
```
Expected output:
- `CLM-DEMO-HEALTH-001 | Rohan Varma | under_review`

```powershell
docker exec claimsage-db psql -U claimsage_app -d claimsage -c "SELECT id, status, current_stage FROM investigation_runs WHERE id = 'f984f980-a782-4880-8a8d-c4dc19400f3e';"
```
Expected output:
- `f984f980-a782-4880-8a8d-c4dc19400f3e | completed | `

---

## 5. Known Limitations & Testing Boundaries

1. **Free-Tier LLM Rate Limits**: Free-tier cloud LLM accounts enforce tight requests/tokens-per-minute limits. The worker includes deliberate pacing delays (`16s`) to prevent rate limit starvation.
2. **Google Gemini Live Availability**:
   - `gemini-2.5-flash` is deprecated for new API keys (returns `404 NOT_FOUND`).
   - `gemini-3.8-flash` is the official Google API model for this API key, but live upstream calls frequently experience `503 UNAVAILABLE` ("model is currently experiencing high demand") or `504 DEADLINE_EXCEEDED` on Google's free preview tier.
   - The test suite verifies full failover to Gemini via mocked HTTP 429 tests, and tests the deterministic fallback report generator when both Groq and Gemini fail.
3. **Email Sandbox Mode**: `EMAIL_BACKEND=sandbox` prevents any real emails from leaving the local environment. Outbound messages are held in `customer_emails` for audit and inspection.
