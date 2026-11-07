# ClaimSage Testing Guide & Verification Standards

ClaimSage enforces strict testing standards to guarantee zero data corruption, reliable mock isolation, and deterministic validation.

---

## 1. Test Database Isolation
Automated tests **never** execute against the development database (`claimsage`). The test configuration strictly enforces:
- `APP_ENV=test`
- `DATABASE_URL` must point to `claimsage_test`.
- The session fixture validates `parsed_url.database == "claimsage_test"` before running.
- In-memory object storage fixture isolates file operations.

---

## 2. Running Automated Tests

### Run the Complete Backend Test Suite
```powershell
$env:CLAIMSAGE_DISABLE_DOTENV="1"
$env:APP_ENV="test"
$env:DATABASE_URL="postgresql+psycopg://claimsage_app:change-this-local-password@127.0.0.1:5432/claimsage_test"
$env:JWT_SECRET_KEY="test-secret-key-at-least-32-chars-long-for-pytest"
$env:GROQ_API_KEY="gsk_test_dummy_key_for_unit_tests_only"
.\.venv\Scripts\pytest.exe backend/tests -q
```
**Expected Outcome**: 784 passed (0 failed, 0 skipped).

### Run Fast Targeted Reliability Tests
```powershell
.\.venv\Scripts\pytest.exe backend/tests/test_llm.py backend/tests/test_config.py backend/tests/test_reliability_remediation.py -q
```
**Expected Outcome**: 74 passed in ~1.1 seconds.

### Run Frontend Typecheck and Production Build
```powershell
cd frontend
npm run typecheck
npm run build
```
**Expected Outcome**: 0 TypeScript errors, production bundle compiled.

---

## 3. Mocked vs Live Provider Testing
- **Mocked Provider Tests**: Tests in `test_llm.py`, `test_agent_graph.py`, and `test_review_report_agent.py` simulate LLM responses, HTTP 429 rate limits, and fallback failovers using synthetic test fixtures. **No real API credits or tokens are consumed.**
- **Live Provider Testing**: Requires valid cloud credentials (`GROQ_API_KEY`, `GEMINI_API_KEY`) and is executed only through controlled smoke scripts (`scripts/groq_smoke_test.py`). Live cloud tests are never run during CI or automated test suites.
