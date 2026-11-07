# ClaimSage REST API Reference & Integration Guide

The ClaimSage REST API is built with FastAPI and runs on port `8000` (or `8080` via the frontend reverse proxy).

---

## 1. Authentication
All endpoints under `/api/v1` (except login and public health checks) require an `Authorization: Bearer <token>` header.

### Authenticate (`POST /api/v1/auth/login`)
- **Request**:
  ```json
  {
    "email": "asha.employee@claimsage.local",
    "password": "EmployeePass123!"
  }
  ```
- **Response**:
  ```json
  {
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "expires_in": 1800
  }
  ```

---

## 2. Core Endpoints

### Claims
- `GET /api/v1/claims` — List claims (filterable by status, type, claimant).
- `POST /api/v1/claims` — Create a synthetic claim record.
- `GET /api/v1/claims/{claim_id}` — Get detailed claim metadata and document list.

### Document & Evidence Upload
- `POST /api/v1/evidence/{claim_id}/upload` — Multipart document upload (PDF/TXT).
- `GET /api/v1/evidence/{claim_id}/documents/{document_id}/preview` — Stream binary document for inline browser viewing.
- `GET /api/v1/evidence/{claim_id}/chunks` — Inspect chunked passages and vector embeddings.

### Policies
- `GET /api/v1/policies` — List policy documents.
- `POST /api/v1/policies/upload` — Ingest versioned policy PDF.
- `GET /api/v1/policies/{policy_id}/clauses` — List extracted clauses and verification statuses.
- `PATCH /api/v1/policies/{policy_id}/clauses/{clause_id}` — Human verification sign-off for a policy clause.

### Investigations
- `POST /api/v1/investigations/{claim_id}/run` — Asynchronously queue an investigation run.
- `GET /api/v1/investigations/{investigation_id}/status` — Poll run status, current stage, and progress.
- `GET /api/v1/investigations/{investigation_id}/report` — Retrieve structured multi-agent report.

### Human Review & Email Sandbox
- `GET /api/v1/customer_emails/claims/{claim_id}` — List drafted follow-up emails.
- `POST /api/v1/customer_emails/draft` — Generate an AI email draft based on missing claim findings.
- `POST /api/v1/customer_emails/{email_id}/send` — Approve and dispatch email to sandbox outbox.
- `POST /api/v1/system/human_reviews` — Record human reviewer decision (`approved`, `escalated`, `info_requested`).

---

## 3. Health & Readiness
- `GET /health/live` — Returns `200 OK` if FastAPI process is responsive.
- `GET /health/ready` — Returns `200 OK` if database and vector dependencies are reachable.
