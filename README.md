# ClaimSage — Enterprise AI-Powered Insurance Claims Investigation Assistant

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Tests](https://img.shields.io/badge/tests-784%20passed-success.svg)]()
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)]()
[![TypeScript](https://img.shields.io/badge/typescript-5.8-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)]()
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2+-purple.svg)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)]()

ClaimSage is an enterprise-grade, evidence-grounded AI insurance investigation platform built for claims adjusters, policy specialists, and claims supervisors. It combines a multi-agent **LangGraph** workflow, **Contextual Hybrid RAG** (dense `pgvector` embeddings + sparse PostgreSQL full-text search with Reciprocal Rank Fusion), deterministic token-budget management, strict source-citation provenance validation, human-in-the-loop review queues, and sandboxed customer communications.

---

## Table of Contents
1. [Problem Statement](#1-problem-statement)
2. [Project Objectives](#2-project-objectives)
3. [Key Capabilities](#3-key-capabilities)
4. [Multi-Agent AI Architecture](#4-multi-agent-ai-architecture)
5. [Specialist Agents and Responsibilities](#5-specialist-agents-and-responsibilities)
6. [LangGraph Orchestration & State Preservation](#6-langgraph-orchestration--state-preservation)
7. [Contextual Hybrid RAG & Retrieval](#7-contextual-hybrid-rag--retrieval)
8. [Technology Stack](#8-technology-stack)
9. [LLM Provider Integration (Groq & Gemini)](#9-llm-provider-integration-groq--gemini)
10. [Human-in-the-Loop Safeguards](#10-human-in-the-loop-safeguards)
11. [Security, Privacy & RBAC](#11-security-privacy--rbac)
12. [Environment Variables](#12-environment-variables)
13. [Docker-Based Quickstart](#13-docker-based-quickstart)
14. [Local Development Setup](#14-local-development-setup)
15. [Database Initialization & Migrations](#15-database-initialization--migrations)
16. [Frontend & Backend Startup](#16-frontend--backend-startup)
17. [API Documentation & Health Endpoints](#17-api-documentation--health-endpoints)
18. [Testing Instructions](#18-testing-instructions)
19. [Synthetic Demo Guide](#19-synthetic-demo-guide)
20. [Known Limitations](#20-known-limitations)
21. [Project Status & Future Roadmap](#21-project-status--future-roadmap)

---

## 1. Problem Statement
Insurance claims adjusters face high cognitive loads when investigating complex claims. In typical health and motor insurance workflows, an investigator must manually cross-reference:
- Disparate unstructured claim documentation (discharge summaries, hospital bills, diagnostic scans, police FIRs, driving licenses, vehicle damage estimates).
- Complex, versioned policy wordings spanning hundreds of pages with intricate coverage schedules, room-rent sub-limits, deductibles, and exclusions.
- Chronological timelines and medical billing discrepancies.

Traditional LLM approaches (such as generic chatbots or unconstrained RAG pipelines) fail in this domain because they hallucinate citations, invent policy rules, lose context during token overflow, or emit legally hazardous declarations (such as autonomous coverage denials or fraud accusations).

## 2. Project Objectives
ClaimSage solves this challenge by implementing an auditable, multi-agent AI copilot designed to:
- **Ground every observation**: Tie every finding directly to canonical document chunks, clause identifiers, and verbatim excerpts.
- **Enforce decision boundaries**: Assist human adjusters without ever autonomously approving, denying, or settling claims.
- **Maintain workflow reliability**: Guard against provider rate limits and context-length exhaustion via deterministic pre-invocation token budgeting and graceful fallback synthesis.
- **Guarantee enterprise privacy**: Ensure no real personal identifying information is transmitted, using strict synthetic demo datasets and sandboxed outbound communications.

## 3. Key Capabilities
- **Multi-Agent Decomposition**: Six specialized AI agents operate with explicit domain boundaries and Pydantic-validated input/output contracts.
- **Contextual Hybrid Retrieval**: Combines dense semantic vector similarity (`sentence-transformers/all-MiniLM-L6-v2` via `pgvector`) with sparse lexical matching (`tsvector` / `ts_rank_cd`) merged via Reciprocal Rank Fusion (RRF).
- **Automated Evidence Reconciliation**: Shared evidence context reconciles document status across specialists before missing-information findings are finalized.
- **Deterministic Token Budget Manager**: Enforces strict per-stage token allocations (`tiktoken`) before making cloud LLM calls, preventing context truncation and out-of-budget API errors.
- **Deterministic Fallback Report Mode**: Generates a complete, structured investigation report from completed specialist outputs even if cloud providers fail or exhaust quotas.
- **Human Review Queue**: Dedicated workflow for claims adjusters to sign off on findings, request additional information, or escalate claims with mandatory audit rationale.
- **Sandboxed Communications**: Outbox pattern for customer follow-up emails, enabling adjusters to inspect and edit drafted inquiries safely.

---

## 4. Multi-Agent AI Architecture

The ClaimSage multi-agent orchestration architecture is powered by **LangGraph**:

```mermaid
flowchart TD
    Start([Launch Investigation]) --> Retrieve[Evidence & Policy Retrieval]
    Retrieve --> Sup[Supervisor Agent]
    Sup --> Intake[Intake Agent]
    Intake --> Evid[Evidence Analyst]
    Evid --> Policy[Policy Analyst]
    Policy --> Route{Claim Type?}
    Route -->|Motor Claim w/ Estimate| Repair[Repair Estimate Analyst]
    Route -->|Health Claim or No Estimate| Risk[Risk & Anomaly Agent]
    Repair --> Risk
    Risk --> Report[Review & Report Agent]
    Report --> EndNode([Persisted Investigation Report])

    subgraph Infrastructure ["Enterprise Infrastructure & Guardrails"]
        TBM["Token Budget Manager"]
        SRL["Shared Rate Limiter (PostgreSQL)"]
        PV["Provenance & Quote Validator"]
        DF["Deterministic Fallback Engine"]
    end
```

---

## 5. Specialist Agents and Responsibilities

| Specialist Agent | Domain Responsibility | Output Schema |
| :--- | :--- | :--- |
| **Supervisor Agent** | Analyzes claim facts, task objectives, and document types; dynamically selects the appropriate specialists. | `SupervisorPlan` |
| **Claim Intake Specialist** | Inspects uploaded claim files, generates document inventories, checks legibility/completeness, and identifies missing intake requirements. | `IntakeDocumentOutput` |
| **Evidence Analyst** | Assembles cross-document clinical or incident timelines, extracts verified facts, identifies conflicting assertions, and flags evidence gaps. | `EvidenceAnalystOutput` |
| **Policy Analyst** | Evaluates applicable policy clauses against claim facts; extracts coverage indicators, exclusions, sub-limits, and conditions with clause provenance. | `PolicyAnalystOutput` |
| **Repair Estimate Analyst** | *(Motor claims only)* Reconciles repair line items, assesses parts depreciation and labor charges, and evaluates estimate totals against deterministic rules. | `RepairEstimateAnalystOutput` |
| **Risk & Anomaly Agent** | Surfaces documentation inconsistencies, billing irregularities, and timeline anomalies while strictly separating verified facts from investigative hypotheses. | `RiskAnomalyOutput` |
| **Review & Report Agent** | Synthesizes all specialist findings into a unified, executive investigation report with JSON Pointer (`output_path`) cross-references and source citations. | `ReviewReportOutput` |

---

## 6. LangGraph Orchestration & State Preservation

- **Sequential & Conditional State Passing**: Investigation state is managed as an immutable `InvestigationState` dictionary flowing through LangGraph nodes.
- **Incremental Result Assembly**: Each agent writes its structured output into `result[agent_key]`. If a downstream agent fails, all upstream specialist outputs remain preserved in the database.
- **State-Level Reconciliation**: Before report generation, `reconcile_specialist_missing_in_state` checks whether facts marked missing by one specialist were actually retrieved by another, preventing contradictory missing-information findings.
- **Resilient Resumption**: The orchestrator can resume or retry only the failed report stage (`retry_failed_report_stage`) without re-running earlier completed specialists.

---

## 7. Contextual Hybrid RAG & Retrieval

ClaimSage implements a Contextual Hybrid Retrieval system (`backend/src/claimsage/rag/contextual_retrieval.py`):

1. **Document Chunking & Storage**: Documents are chunked into 500-character segments with 100-character overlap. Raw files are stored in MinIO S3, while chunks and metadata reside in PostgreSQL.
2. **Dense Semantic Embeddings**: Chunks are embedded using local CPU inference (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions) and stored in `pgvector`.
3. **Sparse Full-Text Indexing**: Each chunk maintains a PostgreSQL `tsvector` with English stemming and dictionary configuration.
4. **Reciprocal Rank Fusion (RRF)**: Dense vector similarity scores and sparse lexical ranks (`ts_rank_cd`) are merged:
   $$RRF\_Score(d) = \sum_{m \in \{dense, sparse\}} \frac{1}{60 + Rank_m(d)}$$
5. **Strict Document Isolation**: Queries are bounded by `claim_id` or authorized `policy_id` filters, preventing cross-tenant data leakage.

---

## 8. Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Frontend** | React 19, TypeScript 5.8, Vite 8, Tailwind CSS v4, TanStack React Query v5, Axios, Lucide Icons |
| **Backend API** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, PyJWT, Pwdlib (Argon2 / Bcrypt) |
| **AI & Orchestration** | LangGraph 1.2+, LangChain Core, `langchain-groq`, `google-genai` SDK, `tiktoken` |
| **RAG & Storage** | PostgreSQL 16 + `pgvector` (`Vector(384)`), `sentence-transformers`, MinIO S3 Object Storage |
| **Infrastructure** | Docker, Docker Compose, Nginx (Alpine), Uvicorn |

---

## 9. LLM Provider Integration (Groq & Gemini)

ClaimSage features a dual-provider architecture:
- **Primary Provider**: **Groq Cloud** running `openai/gpt-oss-120b` via `langchain-groq`.
- **Secondary Fallback Provider**: **Google Gemini** via the official `google-genai` Python SDK.

### Current Implementation Status & Verification Note
- **Groq Integration**: Fully implemented and tested. Cloud rate limits (TPM) on free/developer tiers are handled via pacing delays (`16s`) and automatic `Retry-After` backoff.
- **Gemini Fallback Implementation**: Implemented in `backend/src/claimsage/agents/llm.py` via `GeminiChatModel` and `GeminiStructuredRunnable`.
- **Important Provider Verification Notice**: In offline test suites, Groq success, rate-limiting, and Gemini fallback failover are **fully verified using mocked provider adapters** (784 passing tests). In live API environments, Google AI Studio rejected `gemini-2.5-flash` with HTTP 404 (model deprecated for new users) and `gemini-3.8-flash` with HTTP 429 (daily free-tier quota exhaustion). **Live cloud Gemini execution is therefore unverified pending an active quota allocation.**

---

## 10. Human-in-the-Loop Safeguards

1. **Mandatory Human Review**: The system flag `human_review_required` is hardcoded to `True` across all agent outputs. AI outputs are advisory.
2. **Prohibited Decision Language**: Lexical filters reject generated text attempting to approve, deny, settle, or pay claims, or accusing parties of fraud:
   ```python
   # Excerpt from ReviewReportAgent prohibited language patterns
   r"\b(?:claim|claimant)\b.{0,60}\b(?:approve[sd]?|deny|denied|reject(?:ed)?|pay(?:able|ment)?|settle[sd]?)\b"
   ```
3. **Verbatim Quote Verification**: Report citations must contain exact substrings from retrieved evidence chunks; ungrounded citations are flagged as validation warnings.
4. **Deterministic Fallback Engine**: If providers fail completely, ClaimSage constructs a structured report from completed specialist data, explicitly tagging it `report_generation_mode="deterministic_fallback"`.

---

## 11. Security, Privacy & RBAC

- **Zero Hardcoded Secrets**: No API keys, credentials, or private keys are stored in the repository.
- **Strict Role-Based Access Control (RBAC)**:
  - `claims_adjuster`: View assigned claims, run investigations, draft follow-up emails.
  - `policy_specialist`: Manage policy documents, verify clause extractions.
  - `admin`: System-wide access, audit log inspection, employee management.
- **Enterprise Audit Logging**: Every authentication event, document retrieval, investigation execution, and email draft is permanently recorded in `audit_events`.
- **Synthetic Data Standard**: All demo claims, policies, hospitals, and names are completely synthetic.

---

## 12. Environment Variables

Create `.env` by copying `.env.example`. Never commit `.env` to version control.

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `APP_NAME` | Application identifier | `ClaimSage` |
| `APP_ENV` | Environment (`development`, `test`, `production`) | `development` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://claimsage_app:password@127.0.0.1:5432/claimsage` |
| `JWT_SECRET_KEY` | Secret for signing auth tokens (>=32 chars) | `change-this-jwt-secret-key-minimum-32-chars` |
| `GROQ_API_KEY` | Server-side API key for Groq | `gsk_...` |
| `GROQ_MODEL` | Primary Groq model | `openai/gpt-oss-120b` |
| `GROQ_MAX_OUTPUT_TOKENS` | Maximum completion tokens | `4096` |
| `GROQ_TIMEOUT_SECONDS` | Request timeout | `60.0` |
| `GEMINI_API_KEY` | Fallback Google Gemini API key | `AIzaSy...` |
| `GEMINI_MODEL` | Fallback Gemini model | `gemini-3.8-flash` |
| `EMAIL_BACKEND` | Email mode (`sandbox` or `smtp`) | `sandbox` |
| `STORAGE_BACKEND` | Object storage backend (`s3` or `in_memory`) | `s3` |
| `STORAGE_ENDPOINT_URL` | S3 / MinIO endpoint | `http://minio:9000` |
| `STORAGE_BUCKET_NAME` | Storage bucket name | `claimsage-documents` |

---

## 13. Docker-Based Quickstart

### 1. Configure Environment
```bash
cp .env.example .env
# Edit .env and supply your GROQ_API_KEY and a secure JWT_SECRET_KEY
```

### 2. Build and Start All Containers
```bash
docker compose up -d --build
```

### 3. Verify Container Status
```bash
docker compose ps
```
All containers (`claimsage-frontend`, `claimsage-backend`, `claimsage-worker`, `claimsage-db`, `claimsage-minio`) should report healthy.

- **Frontend Application**: `http://localhost:8080`
- **Backend Health Check**: `http://localhost:8080/health/ready`

---

## 14. Local Development Setup

### 1. Start Database & MinIO via Docker
```bash
docker compose up -d db minio
```

### 2. Set Up Python Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e "./backend[dev]"
```

### 3. Set Up Frontend
```powershell
cd frontend
npm install
npm run dev
```

---

## 15. Database Initialization & Migrations

Database tables and extensions (`pgvector`) are managed through Alembic migrations.

### Run Migrations
```powershell
cd backend
$env:PYTHONPATH="src"
alembic upgrade head
```

### Seed Demo Scenarios & Policies
```powershell
python scripts/seed_demo.py
python scripts/embed_pending_chunks.py
```

---

## 16. Frontend & Backend Startup

### Start Backend API Server
```powershell
$env:PYTHONPATH="backend/src;backend"
uvicorn claimsage.main:app --host 127.0.0.1 --port 8000 --reload
```

### Start Asynchronous Investigation Worker
```powershell
$env:PYTHONPATH="backend/src;backend"
python -u backend/scripts/run_investigation_worker.py
```

---

## 17. API Documentation & Health Endpoints

When running locally or via Docker:
- **Interactive Swagger Documentation**: `http://localhost:8080/docs`
- **ReDoc Documentation**: `http://localhost:8080/redoc`
- **OpenAPI Schema**: `http://localhost:8080/openapi.json`
- **Liveness Probe**: `http://localhost:8080/health/live`
- **Readiness Probe**: `http://localhost:8080/health/ready`

---

## 18. Testing Instructions

Automated backend tests run against the isolated `claimsage_test` database. Tests strictly refuse to execute against the production/dev database.

### Run Full Backend Test Suite
```powershell
$env:CLAIMSAGE_DISABLE_DOTENV="1"
$env:APP_ENV="test"
$env:DATABASE_URL="postgresql+psycopg://claimsage_app:change-this-local-password@127.0.0.1:5432/claimsage_test"
$env:JWT_SECRET_KEY="test-secret-key-at-least-32-chars-long-for-pytest"
$env:GROQ_API_KEY="gsk_test_dummy_key_for_unit_tests_only"
.\.venv\Scripts\pytest.exe backend/tests -q
```
**Result**: `784 passed in 2262s (0:37:42)`.

### Run Fast Targeted Reliability Tests
```powershell
.\.venv\Scripts\pytest.exe backend/tests/test_llm.py backend/tests/test_config.py backend/tests/test_reliability_remediation.py -q
```
**Result**: `74 passed in 1.14s`.

### Run Frontend Typecheck and Build
```powershell
cd frontend
npm run typecheck
npm run build
```
**Result**: `✓ built in 1.63s (0 errors)`.

---

## 19. Synthetic Demo Guide

1. Log in to `http://localhost:8080` using one of the pre-configured demo credentials:
   - **Claims Adjuster**: `asha.employee@claimsage.local` / `EmployeePass123!`
   - **Policy Specialist**: `priya.policy@claimsage.local` / `PolicyPass123!`
   - **Supervisor / Admin**: `admin@claimsage.local` / `AdminPass123!`
2. Navigate to **Claims** -> **`CLM-DEMO-HEALTH-001`** (*Rohan Varma*, Health claim under policy **`DEMO-HEALTH-SECURE-2026-V3`**).
3. Inspect uploaded documents in the inline viewer (Itemized Bill, Discharge Summary, Prescription).
4. Inspect the Policy Knowledge Base clauses under **Policies**.
5. Launch an investigation and monitor real-time worker execution through the interactive dashboard.
6. Review the synthesized investigation report, examine source citations, and submit a review sign-off in the **Review Queue**.

---

## 20. Known Limitations

- **Provider Rate Limits**: Free-tier cloud LLM accounts enforce tight requests/tokens-per-minute limits. The worker includes deliberate pacing delays (`16s`) to stay within quotas.
- **Gemini Free-Tier Availability**: The Google AI Studio free tier limits requests to 20 per day for preview models, requiring a standard tier key for high-volume automated testing.
- **Sandbox Email Delivery**: By default, customer emails are held in `EMAIL_BACKEND=sandbox` for compliance and audit safety.

---

## 21. Project Status & Future Roadmap

- [x] Complete multi-agent LangGraph workflow with 6 specialist agents
- [x] Hybrid dense/sparse contextual RAG with Reciprocal Rank Fusion
- [x] Deterministic token budgeting and DB-backed rate limiting
- [x] Deterministic fallback report synthesis engine
- [x] Full React 19 + TypeScript web application
- [x] Enterprise RBAC, audit logging, and document preview
- [ ] Multi-region S3 document replication
- [ ] Active-active multi-worker clustering via Redis stream coordination
- [ ] Extended OCR processing pipeline for handwritten medical prescriptions
