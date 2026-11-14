# ClaimSage — AI Insurance Employee Assistant

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2+-7C3AED)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

**ClaimSage** is an internal, evidence-grounded **AI Insurance Employee Assistant** built to support insurance operations teams investigating **health insurance claims** (with additional support for motor claim repair-estimate analysis). It combines a multi-agent **LangGraph** workflow, **Two-Pass Contextual Dense RAG** over **PostgreSQL 16 + `pgvector`**, deterministic **token-budget management**, verbatim citation verification, and a strict **human-in-the-loop review boundary**.

### Problem Statement
During claim evaluation, insurance employees must cross-reference unstructured claimant documents (hospital discharge summaries, itemized hospital bills, clinical notes, diagnostic reports) against versioned insurance policy wordings containing waiting periods, room-rent sub-limits, coverage schedules, and exclusions. Performing this cross-check manually is slow and error-prone, while generic chatbot wrappers around large language models (LLMs) risk hallucinating policy clauses, dropping critical evidence due to context-window limits, or emitting unauthorized claim decisions.

ClaimSage addresses this by transforming unstructured claim files and policy documents into **structured, source-cited investigation findings and reports** while ensuring that **only authorized human reviewers can record final review decisions**.

### Target Users
- **Claims Adjusters (`CLAIMS_ADJUSTER`)**: Inspect assigned claims, upload and download claim evidence PDFs, inspect applicable policy clauses and exclusions, launch and monitor AI investigations, edit findings with an immutable audit history, and draft sandboxed follow-up emails.
- **Policy Specialists (`POLICY_SPECIALIST`)**: Manage the policy knowledge base, upload policy PDFs, and verify extracted policy clauses.
- **Team Leads (`TEAM_LEAD`)**: Supervise team-assigned claims and monitor investigation queues within their team boundary.
- **Administrators / Authorized Reviewers (`ADMIN`)**: Oversee all claims, policies, and audit trails, and execute final human review decisions (`approved`, `needs_additional_documents`, `returned_for_investigation`, `escalated`).

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Key Features](#2-key-features)
3. [Technology Stack](#3-technology-stack)
4. [Technical Architecture Overview](#4-technical-architecture-overview)
5. [System Architecture Diagram](#5-system-architecture-diagram)
6. [End-to-End Claim Investigation Workflow](#6-end-to-end-claim-investigation-workflow)
7. [RAG Architecture — Ingestion & Contextual Retrieval](#7-rag-architecture--ingestion--contextual-retrieval)
8. [LangGraph Multi-Agent Architecture](#8-langgraph-multi-agent-architecture)
9. [LangChain vs LangGraph vs RAG](#9-langchain-vs-langgraph-vs-rag)
10. [Human-in-the-Loop and Responsible AI](#10-human-in-the-loop-and-responsible-ai)
11. [Security and Data Protection](#11-security-and-data-protection)
12. [Project Screenshots](#12-project-screenshots)
13. [Project Structure](#13-project-structure)
14. [Installation and Local Setup](#14-installation-and-local-setup)
15. [Demo Walkthrough](#15-demo-walkthrough)
16. [Testing and Verification](#16-testing-and-verification)
17. [Known Limitations](#17-known-limitations)
18. [Future Improvements](#18-future-improvements)
19. [Author & Supporting Documentation](#19-author--supporting-documentation)

---

## 1. Project Overview

### Operational Challenge in Claims Processing
When a policyholder submits a health insurance reimbursement claim—for example, a three-day inpatient hospitalization for an emergency laparoscopic appendectomy—an employee must verify several evidence-dependent questions before any decision can be made:
1. **Document Completeness**: Were both the hospital discharge summary and the itemized hospital bill submitted, and are all pages readable?
2. **Factual & Timeline Consistency**: Do the admission and discharge dates on the hospital bill match the discharge summary and the reported loss date on the claim?
3. **Policy Applicability & Sub-Limits**: Was the policy version active on the loss date? Does inpatient hospitalization coverage apply ($\ge 24$ hours), and do daily room-rent charges (e.g., INR 4,500/day) comply with the policy's room-rent sub-limit (e.g., INR 5,000/day)?
4. **Evidence Gaps**: What supporting clinical or pre-authorization records are still missing and need to be requested from the policyholder?

### How ClaimSage Assists Employees
Instead of using a single monolithic prompt, ClaimSage processes investigations asynchronously through a durable background worker and a **9-node LangGraph workflow**:
- **Authorization-First RAG**: Before generating embeddings or querying vectors, ClaimSage verifies that the employee is authorized to access the claim and resolves the exact policy version effective on the claim's loss date.
- **Domain Specialist Decomposition**: A Supervisor node plans execution across specialized agents (**Intake & Document Agent**, **Evidence Analyst**, **Policy Analyst**, **Repair Estimate Analyst** when applicable, and **Risk & Anomaly Agent**), followed by cross-specialist evidence reconciliation and a **Review & Report Agent**.
- **Provenance & Verbatim Quote Validation**: Every factual observation, policy clause finding, and anomaly must cite a retrieved `chunk_id` and include a verbatim quote verified against the source text (`quote_matches_evidence`).
- **Mandatory Human Review**: Every generated report enforces `human_review_required = True` and runs lexical guardrails that block autonomous approval, denial, settlement, or fraud-accusation language.

### Core Engineering Highlights
- **Custom SQL-Scoped Vector Retrieval**: Rather than delegating retrieval to an opaque framework chain, ClaimSage executes SQL-level tenant isolation, loss-date policy applicability filtering, two-pass contextual gap-filling, per-document diversity caps, and SHA-256 content deduplication directly over PostgreSQL + `pgvector`.
- **Deterministic Token Budgeting & Multi-Provider Failover**: `TokenBudgetManager` counts prompt and JSON-schema tokens via `tiktoken` before every LLM call. `invoke_structured` coordinates rate limits across processes via PostgreSQL, invokes **Groq (`openai/gpt-oss-120b`)** as primary, fails over to **Google Gemini (`gemini-3.8-flash`)** with automatic JSON-schema sanitization (`_sanitize_gemini_json_schema`), and falls back to a deterministic report builder if both cloud providers are unreachable.
- **Durable PostgreSQL Job Queue**: Long-running multi-agent investigations execute outside the HTTP request cycle using `SELECT ... FOR UPDATE SKIP LOCKED`, lease expiration timestamps, background heartbeat threads, worker fencing, and node-level state snapshots (`state_snapshot` JSONB).

---

## 2. Key Features

All features listed below are implemented in source code and verified in the local environment:

### Claim Management
- View, filter, and inspect health and motor insurance claims (`GET /api/v1/claims`, `GET /api/v1/claims/{claim_id}`).
- Link claims to specific insurer, product, and policy identifiers with loss-date validation.

### Evidence & Document Management
- Upload PDF claim evidence (`POST /api/v1/claims/{claim_id}/evidence`) with strict validation (`.pdf` extension, `%PDF-` magic header check, 20 MiB parser cap, unencrypted check, page-count cap).
- Store original PDFs in **MinIO** S3-compatible object storage (`claimsage-documents` bucket) with SHA-256 checksum verification upon download.
- Extract native PDF text via `pypdf` with automatic **PyMuPDF (`fitz`) + Tesseract OCR** fallback for image-only pages.

### AI-Powered Investigation
- Asynchronous investigation execution coordinated by **LangGraph** (`InvestigationState`).
- Supervisor-driven specialist selection with deterministic fallback planning if the Supervisor LLM call fails.
- Node-by-node progress persistence (`current_stage`, `state_snapshot`) and stage-level diagnostics (token counts, execution duration, provider/model used, retry attempts).

### Policy Analysis
- Versioned policy registry (`policy_documents`, `policy_clauses`, `policy_coverages`, `policy_exclusions`, `policy_chunks`).
- Automatic resolution of the single unambiguous policy version effective on the claim's loss date.
- Specialist comparison of hospital billing items (such as daily room rent) against policy sub-limits, waiting periods, and exclusions.

### Evidence Retrieval & Citations
- Local 384-dimensional dense embeddings (`sentence-transformers/all-MiniLM-L6-v2`) stored in PostgreSQL `pgvector` (`Vector(384)`).
- Two-pass contextual retrieval (`ContextualRetrievalService`) that backfills missing critical document types (e.g., hospital bill or discharge summary) or room-rent sub-limit clauses.
- Relational finding-reference resolution (`investigation_finding_references`) supporting both UUID primary keys and 64-character SHA-256 chunk hashes with document, page, and passage provenance.

### Risk & Anomaly Analysis
- Cross-references structured claim metadata, retrieved evidence chunks, and completed specialist outputs to surface date/amount inconsistencies, hypotheses requiring verification, and missing information.
- Enforces regex guardrails (`_PROHIBITED_DECISION_PATTERNS`) that reject outputs containing autonomous coverage determinations or accusations of fraud.
- Includes deterministic arithmetic verification (`Decimal` rules in `repair_estimate_rules.py`) for motor repair estimates.

### Investigation Reports
- Cross-specialist evidence reconciliation (`reconcile_specialist_missing_in_state`) prevents one agent from flagging a document as missing when another agent has already extracted facts from it.
- Synthesizes results into five structured report categories: `observed_facts`, `analyst_interpretations`, `hypotheses`, `conflicting_findings`, and `missing_information`, plus `specialist_coverage` and `source_inventory`.
- Tertiary deterministic fallback report builder (`build_fallback_partial_report`) preserves completed specialist findings if cloud LLM synthesis fails.

### Human-in-the-Loop Review
- Dedicated **Review Queue** and review submission workflow (`POST /api/v1/agent/investigations/{investigation_id}/reviews`).
- Original AI findings in `investigation_findings` remain immutable; human revisions are stored as versioned records in `investigation_finding_edits` with mandatory rationale.

### Role-Based Access Control (RBAC)
- Four distinct roles (`CLAIMS_ADJUSTER`, `POLICY_SPECIALIST`, `TEAM_LEAD`, `ADMIN`) enforced server-side on every API route and database query.
- Claims Adjusters have read-only access to authorized policy clauses (`BUG-03` verified) and are blocked (`403 Forbidden`) from verifying clauses, modifying policies, or submitting final human review decisions.

### Audit Trail
- Immutable `audit_events` table recording authentication, claim access, evidence uploads, investigation lifecycle transitions, finding edits, and human review decisions with correlation IDs.

### Email Notification Sandbox
- Outbox pattern (`customer_emails` and `notification_deliveries`) with `EMAIL_BACKEND=sandbox` enabled by default so drafted policyholder follow-up requests and internal notifications are persisted for inspection without sending real external emails.

### Background Investigation Processing
- Standalone Python worker (`InvestigationWorker`) polling PostgreSQL with `FOR UPDATE SKIP LOCKED`, 120-second leases, 40-second background heartbeats, optimistic worker fencing (`WorkerFencedError`), and bounded retries (`max_attempts = 3`).

---

## 3. Technology Stack

Only technologies present and active in the repository are listed below:

| Layer | Technology | Role in ClaimSage |
| :--- | :--- | :--- |
| **Frontend** | React 19.3, TypeScript 5.9, Vite 8.3, Tailwind CSS v4, TanStack React Query v5, TanStack Table v9, React Router v7, React Hook Form + Zod, Axios, Lucide Icons, Recharts, Motion, Sonner | Single-page employee workspace served by Nginx (`:8080`) with reverse proxy to the backend API |
| **Backend** | Python 3.12, FastAPI 0.115+, Uvicorn, Pydantic v2 (`pydantic-settings`), SQLAlchemy 2.0, Alembic, `psycopg` v3 | REST API, dependency injection, schema validation, ORM persistence, and database migrations |
| **Database** | PostgreSQL 16 (`pgvector/pgvector:pg16`) | Primary relational store across 21 tables for claims, policies, investigations, audit logs, and queue leases |
| **Vector Search** | `pgvector` (`Vector(384)`) with SQL `cosine_distance` | Stores 384-dimensional chunk embeddings for claim evidence and policy documents inside PostgreSQL |
| **Document Storage & OCR** | MinIO (`boto3` S3 client), `pypdf`, PyMuPDF (`fitz`), `pytesseract` (Tesseract OCR), Pillow | Stores raw PDFs with SHA-256 verification and extracts native or OCR text page-by-page |
| **AI Orchestration** | LangGraph 1.2+ (`StateGraph`) | Stateful 9-node multi-agent investigation graph with conditional routing and progress streaming |
| **LLM Providers** | **Groq Cloud** (`langchain-groq`, primary model `openai/gpt-oss-120b`), **Google Gemini** (`google-genai` SDK, fallback model `gemini-3.8-flash`) | Structured JSON generation with automatic retry, rate-limit coordination, and secondary provider failover |
| **Embedding Model & Tokenizer** | `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU), `tiktoken` (`o200k_harmony` / `cl100k_base`) | Local semantic vector generation and deterministic per-stage input token budgeting |
| **Authentication & Security** | `PyJWT` (`HS256`), `pwdlib` (`Argon2id`) | Stateless JWT bearer authentication and Argon2id password hashing |
| **Background Processing** | Custom PostgreSQL Durable Queue + `InvestigationWorker` | Asynchronous job claiming (`FOR UPDATE SKIP LOCKED`), lease heartbeats, and crash recovery |
| **Infrastructure** | Docker, Docker Compose, Nginx 1.27 (Alpine) | Multi-container local orchestration (`db`, `minio`, `migrate`, `backend`, `worker`, `frontend`) |

---

## 4. Technical Architecture Overview

ClaimSage is architected as a decoupled, multi-container system where synchronous web requests, binary object storage, relational + vector persistence, and long-running multi-agent LLM workflows operate with clear isolation boundaries:

### 1. Frontend & API Gateway Boundary
The user interface is a **React 19 + TypeScript** single-page application served by **Nginx** on port `8080` (`claimsage-frontend`). Nginx serves static assets and reverse-proxies `/api/` and `/health/` traffic to the **FastAPI** backend (`claimsage-backend` on internal port `8000`). FastAPI validates `HS256` JWT bearer tokens, enforces role-based and team-based access controls, and uses **Pydantic v2** schemas to validate both REST payloads and structured LLM outputs.

### 2. Unified Relational & Vector Persistence (`PostgreSQL 16 + pgvector`)
Rather than maintaining a separate external vector database, ClaimSage stores its 21 relational tables (`claims`, `policy_documents`, `policy_clauses`, `investigation_runs`, `audit_events`) alongside `Vector(384)` embeddings (`claim_evidence_chunks`, `policy_chunks`) inside a single **PostgreSQL 16** instance. This design allows retrieval queries to join RBAC filters, claim tenancy (`ClaimEvidenceDocument.claim_id == claim_id`), and policy effective-date applicability (`effective_from <= loss_date <= effective_to`) **within the same SQL transaction** as `pgvector` `cosine_distance` ranking, eliminating cross-store consistency drift. Raw PDF binaries are stored separately in **MinIO** (`claimsage-documents` bucket) and verified via SHA-256 checksums on upload and download.

### 3. Asynchronous Durable Worker Queue
Multi-agent LLM investigations require multiple sequential model calls and take 15–90 seconds to complete. Executing them inside an HTTP request thread would cause gateway timeouts and lost work on transient failures. Instead:
- FastAPI enqueues an `InvestigationRun` record with `status="running"` and `current_stage="queued"`.
- A standalone Python worker (`claimsage-worker`) polls PostgreSQL using `SELECT ... FOR UPDATE SKIP LOCKED`, acquires a 120-second lease (`lease_expires_at`), and spawns a daemon heartbeat thread (`_HeartbeatRunner`) that renews the lease every 40 seconds.
- After each LangGraph node completes, `save_progress()` checks optimistic worker fencing (`WorkerFencedError`) and checkpoints `current_stage` and `state_snapshot` (JSONB) to PostgreSQL so interrupted runs can resume without re-running completed stages.

### 4. Multi-Provider LLM Resilience & Deterministic Guardrails
All specialist LLM invocations pass through `invoke_structured()` in [`backend/src/claimsage/agents/llm.py`](backend/src/claimsage/agents/llm.py):
- **Pre-Call Token Budgeting**: `TokenBudgetManager` counts prompt and JSON-schema tokens via `tiktoken` and compacts retrieved passages so requests never exceed per-stage token ceilings.
- **Distributed Rate Coordination**: A PostgreSQL-backed shared rate limiter (`get_shared_rate_limiter()`) coordinates token-per-minute permits and provider cooldown windows across processes.
- **Three-Tier Provider Hierarchy**:
  1. **Primary Provider**: **Groq Cloud** (`openai/gpt-oss-120b`) via `ChatGroq.with_structured_output()`.
  2. **Secondary Provider**: **Google Gemini** (`gemini-3.8-flash`) via the official `google-genai` SDK (`GeminiChatModel`), triggered automatically on HTTP `429`, quota exhaustion, `5xx` errors, or malformed responses. `_sanitize_gemini_json_schema()` strips `additionalProperties` for Gemini API compatibility before re-validating the response against strict Pydantic models (`extra="forbid"`).
  3. **Tertiary Deterministic Fallback**: If both cloud providers are unavailable during final report synthesis, `build_fallback_partial_report()` constructs a deterministic partial report from the completed specialist outputs so no investigation findings are lost.

---

## 5. System Architecture Diagram

```mermaid
flowchart TD
    subgraph ClientLayer ["Employee Browser"]
        UI["React 19 + TypeScript SPA\n(http://localhost:8080)"]
    end

    subgraph WebTier ["Frontend & API Tier (Docker Network)"]
        Nginx["Nginx Reverse Proxy\n(claimsage-frontend :8080)"]
        API["FastAPI Backend\n(claimsage-backend :8000)"]
        AuthRBAC["JWT Authentication & RBAC\n(Argon2id + Claim/Policy Access Filters)"]
    end

    subgraph DataTier ["Persistence & Storage Tier"]
        PG[("PostgreSQL 16 + pgvector\n21 Relational Tables + Vector(384)\nDurable Queue & Rate Limiter")]
        MinIO[("MinIO Object Storage\nBucket: claimsage-documents\n(Raw PDFs + SHA-256 Verification)")]
    end

    subgraph WorkerTier ["Asynchronous Investigation Engine"]
        Worker["Background Investigation Worker\n(FOR UPDATE SKIP LOCKED + Heartbeats)"]
        Graph["LangGraph StateGraph\n(9-Node Multi-Agent Workflow)"]
        RAG["Two-Pass Contextual Dense RAG\n(all-MiniLM-L6-v2 + TokenBudgetManager)"]
    end

    subgraph LLMTier ["Cloud LLM Providers & Guardrails"]
        Groq["Primary LLM: Groq Cloud\n(openai/gpt-oss-120b)"]
        Gemini["Fallback LLM: Google Gemini\n(gemini-3.8-flash)"]
        DetFallback["Tertiary Deterministic Fallback\n(build_fallback_partial_report)"]
    end

    subgraph ReviewTier ["Governance & Communications"]
        Report["Structured Findings & Report\n(human_review_required = True)"]
        HumanReview["Authorized Human Review (ADMIN)\n& Sandboxed Email Outbox"]
    end

    UI -->|"HTTPS / HTTP :8080"| Nginx
    Nginx -->|"Proxy /api/v1 & /health"| API
    API --> AuthRBAC
    AuthRBAC -->|"SQLAlchemy / psycopg3"| PG
    AuthRBAC -->|"boto3 S3 API"| MinIO
    AuthRBAC -->|"Enqueue InvestigationRun (queued)"| PG

    Worker -->|"Poll & Lease Job + Heartbeat"| PG
    Worker -->|"Execute run_investigation()"| Graph
    Graph -->|"Claim & Policy Vector Search"| RAG
    RAG -->|"SQL Authorization + cosine_distance"| PG
    Graph -->|"invoke_structured() Primary"| Groq
    Groq -.->|"Failover on 429 / 5xx / Malformed"| Gemini
    Gemini -.->|"If Both Providers Unavailable"| DetFallback
    Graph -->|"Persist Stage Snapshots & Findings"| PG
    PG --> Report
    Report -->|"Inspect in UI & Submit Review"| HumanReview
    HumanReview -->|"Record Review / Draft Sandbox Email"| PG
```

### Component Interaction Summary
1. **Browser to Backend**: The React 19 SPA is served by `claimsage-frontend` (Nginx on port `8080`), which reverse-proxies `/api/` and `/health/` requests to `claimsage-backend` (FastAPI on internal port `8000`).
2. **Authentication, Storage & Queueing**: FastAPI authenticates requests using `HS256` JWT bearer tokens and enforces role and claim-level access (`claim_access.py`, `document_access.py`). Uploaded PDFs are stored in **MinIO**, while extracted chunks, 384-dimensional embeddings, and queued `InvestigationRun` rows are written to **PostgreSQL 16**.
3. **Worker & LangGraph Execution**: `claimsage-worker` claims queued jobs from PostgreSQL using row-level locks (`FOR UPDATE SKIP LOCKED`), runs a background heartbeat thread, and executes the **LangGraph** workflow. Each specialist node queries PostgreSQL via the **Two-Pass Contextual Dense RAG** service, compacts passages through `TokenBudgetManager`, and calls **Groq** (or **Google Gemini** on failover).
4. **Persistence & Human Review**: Completed findings (`investigation_findings`), relational source links (`investigation_finding_references`), and the synthesized report (`investigation_reports`) are persisted to PostgreSQL for employee inspection and **Admin** human review.

---

## 6. End-to-End Claim Investigation Workflow

```mermaid
flowchart TD
    Step1["1. Employee Selects Claim in UI\n(e.g., CLM-DEMO-HEALTH-001)"]
    Step2["2. Backend Validates JWT & Claim Access\n(POST /api/v1/agent/claims/{id}/investigations)"]
    AccessCheck{"Authorized?"}
    Deny403["Return 401 / 403 / 404\n(No Investigation Created)"]
    Step3["3. Investigation Enqueued in PostgreSQL\n(status='running', current_stage='queued')"]
    Step4["4. Worker Claims Job via SKIP LOCKED\n(Sets worker_id, 120s Lease & 40s Heartbeat)"]
    Step5["5. LangGraph Workflow Starts\n(investigate + retrieve_claim_evidence)"]
    Step6["6. Supervisor Plans Specialist Execution\n(LLM Plan or Deterministic All-Available Fallback)"]
    Step7["7. Specialists Analyze Context Sequentially\n(Intake -> Evidence -> Policy -> [Estimate] -> Risk)"]
    Reconcile["8. Cross-Specialist Evidence Reconciliation\n& Review Report Synthesis"]
    ReportLLMCheck{"Report LLM\nSucceeded?"}
    AIReport["Validated AI ReviewReportOutput\n(Quotes & Citations Verified)"]
    FallbackReport["Deterministic Partial Report\n(Preserves Specialist Findings)"]
    Step8["9. Persist Findings, Provenance References\n& Report + Sandbox Notifications"]
    WorkerRetryCheck{"Unhandled Worker\nException?"}
    RetryQueue["Release Lease & Re-Queue\n(If attempt_count < max_attempts)"]
    FailRun["Mark Investigation Failed\n(If Max Retries Exceeded)"]
    Step10["10. Adjuster Reviews Report, Citations\n& Specialist Tabs in Browser"]
    Step11["11. Authorized Reviewer (ADMIN) Submits\nFinal Human Review Decision"]

    Step1 --> Step2 --> AccessCheck
    AccessCheck -->|"No"| Deny403
    AccessCheck -->|"Yes"| Step3 --> Step4 --> Step5
    Step5 --> Step6 --> Step7 --> Reconcile --> ReportLLMCheck
    ReportLLMCheck -->|"Yes"| AIReport --> Step8
    ReportLLMCheck -->|"No (Provider Outage)"| FallbackReport --> Step8
    Step5 -.->|"Runtime Error"| WorkerRetryCheck
    Step7 -.->|"Runtime Error"| WorkerRetryCheck
    WorkerRetryCheck -->|"Retry Eligible"| RetryQueue --> Step4
    WorkerRetryCheck -->|"Max Attempts (3) Reached"| FailRun
    Step8 --> Step10 --> Step11
```

### Investigation Lifecycle Stages
1. **Dispatch & Access Control**: When an employee initiates an investigation on a claim, FastAPI verifies claim authorization and checks for any already-active investigation before inserting an `InvestigationRun` row with `status="running"` and `current_stage="queued"`.
2. **Lease Acquisition & Heartbeats**: `InvestigationWorker.claim_next_job()` atomically locks the oldest eligible job using `SELECT ... FOR UPDATE SKIP LOCKED`, increments `attempt_count`, sets a 120-second `lease_expires_at`, and starts a daemon `_HeartbeatRunner` thread that renews the lease every 40 seconds.
3. **Stateful Execution & Fault Tolerance**: As each LangGraph node finishes, `save_progress()` verifies worker ownership (preventing split-brain writes via `WorkerFencedError`) and checkpoints `current_stage` and `state_snapshot` to PostgreSQL. If a transient error interrupts the worker before completion and `attempt_count < max_attempts` (`3`), the lease is released (`current_stage="queued"`) so the job can be safely resumed from its saved snapshot.
4. **Report Persistence & Review**: Once `review_report` completes (either via AI synthesis or `build_fallback_partial_report`), `finish_investigation()` writes all structured findings, resolves chunk/clause foreign keys in `investigation_finding_references`, persists the `InvestigationReport`, queues sandboxed notifications (`INVESTIGATION_COMPLETED` and `HUMAN_REVIEW_REQUIRED`), and marks the run ready for human review.

---

## 7. RAG Architecture — Ingestion & Contextual Retrieval

> **Overview of RAG in ClaimSage**
> *Retrieval-Augmented Generation (RAG) enables the specialist agents to retrieve relevant passages from claim evidence and policy documents before generating their outputs. This grounds the analysis in verifiable source documents rather than relying on the LLM's parametric memory.*

```mermaid
flowchart TD
    subgraph StageA ["Stage A: Document Ingestion & Vector Indexing"]
        Upload["1. PDF Upload\n(Claim Evidence or Policy PDF)"]
        Validate["2. Security & Format Validation\n(.pdf, %PDF- header, <=20 MiB, unencrypted)"]
        StoreMinIO["3. Compute SHA-256 & Store Original PDF\nin MinIO (claimsage-documents)"]
        Extract["4. Page-by-Page Text Extraction\npypdf Native Text -> PyMuPDF + Tesseract OCR Fallback"]
        Chunk["5. Page-Bounded Chunking\n(1,000 chars, 150-char overlap, word-boundary split)"]
        Provenance["6. Deterministic Provenance Identity\nSHA-256(doc_sha256:page:chunk_idx:text)"]
        EmbedDoc["7. Local CPU Embedding Generation\nsentence-transformers/all-MiniLM-L6-v2 (384-dim)"]
        PersistVec[("8. Persist in PostgreSQL 16 + pgvector\nclaim_evidence_chunks / policy_chunks Vector(384)")]

        Upload --> Validate --> StoreMinIO --> Extract --> Chunk --> Provenance --> EmbedDoc --> PersistVec
    end

    subgraph StageB ["Stage B: Two-Pass Contextual Retrieval & Grounded Generation"]
        Context["1. Specialist Node Receives Investigation Context\n(employee_id, claim_id, stage, task)"]
        AuthSQL["2. Pre-Retrieval Authorization & Policy Version Resolution\n(Verify Claim Access + Loss-Date Effective Policy)"]
        EmbedQuery["3. Build Stage-Tailored Query & Generate 384-dim Query Vector\n(all-MiniLM-L6-v2 Normalized Embedding)"]
        Pass1["4. Pass 1: pgvector Cosine Similarity Search in SQL\n(1 - cosine_distance >= min_similarity + Per-Doc Diversity Cap)"]
        Pass2Check{"5. Critical Doc Type\nor Sub-Limit Missing?"}
        Pass2["6. Pass 2: Targeted Gap-Filling Query\n(e.g., hospital_bill, discharge_summary, or Room Rent Sub-Limit)"]
        Dedup["7. Deduplicate Passages\n(By chunk_id UUID + Normalized Text SHA-256 Hash)"]
        Budget["8. TokenBudgetManager Compaction (tiktoken)\n(Prioritize Mandatory Passages + Fit Stage Input Budget)"]
        LLMCall["9. Invoke Specialist LLM with Grounded Passages\n(Strict Pydantic Schema Output)"]
        VerifyQuote["10. Verify Cited chunk_ids & Verbatim Quotes\n(quote_matches_evidence + Relational Provenance Link)"]

        Context --> AuthSQL --> EmbedQuery --> Pass1 --> Pass2Check
        Pass2Check -->|"Yes (Evidence / Risk / Policy)"| Pass2 --> Dedup
        Pass2Check -->|"No"| Dedup
        Dedup --> Budget --> LLMCall --> VerifyQuote
    end

    PersistVec -.->|"Queried During Investigation"| Pass1
```

### Verified RAG Implementation Details
| RAG Component | Implementation in ClaimSage | Source File |
| :--- | :--- | :--- |
| **PDF Validation & Extraction** | Checks `.pdf` suffix, `%PDF-` signature in first 1,024 bytes, `MAX_PDF_SIZE_BYTES = 20 MiB`, unencrypted status, and `pdf_max_pages`. Extracts native text per page via `pypdf.PdfReader`; if a page has no extractable text, renders at 200 DPI via PyMuPDF (`fitz`) and runs `pytesseract` OCR. | [`document_loader.py`](backend/src/claimsage/rag/document_loader.py), [`ocr_service.py`](backend/src/claimsage/rag/ocr_service.py) |
| **Chunking Configuration** | **`1,000` characters** per chunk (`chunk_size = 1000`) with **`150` characters** overlap (`overlap = 150`), split on word boundaries without crossing PDF page boundaries. | [`document_loader.py`](backend/src/claimsage/rag/document_loader.py) |
| **Embedding Model & Dimensions** | **`sentence-transformers/all-MiniLM-L6-v2`** producing normalized **`384`-dimensional** dense vectors on CPU (`MAX_BATCH_SIZE = 64`). | [`embedding_service.py`](backend/src/claimsage/rag/embedding_service.py) |
| **Vector Storage & Metric** | Stored in PostgreSQL 16 `pgvector` `Vector(384)` columns (`claim_evidence_chunks.embedding` and `policy_chunks.embedding`). Ranked in SQL via **dense cosine similarity** (`1.0 - embedding.cosine_distance(query_vector)`). *(Note: BM25, PostgreSQL `tsvector`, Reciprocal Rank Fusion, and HNSW indexes are not used.)* | [`evidence_retrieval_service.py`](backend/src/claimsage/rag/evidence_retrieval_service.py), [`retrieval_service.py`](backend/src/claimsage/rag/retrieval_service.py) |
| **Per-Document Diversity & Two-Pass Retrieval** | `search_claim_evidence` fetches `max(top_k * 3, 15)` candidates and applies a per-document cap (`max(1, top_k // 2)`) before backfilling so a single long PDF cannot crowd out other documents. `ContextualRetrievalService` executes a **second pass** (`_claim_second_pass` / `_policy_second_pass`) if critical document types (`hospital_bill`, `discharge_summary`, `repair_estimate`) or health policy room-rent sub-limit clauses (`INR 5,000`) are absent from Pass 1. | [`contextual_retrieval.py`](backend/src/claimsage/rag/contextual_retrieval.py) |
| **Token Budget Management** | `TokenBudgetManager` uses `tiktoken` (`o200k_harmony` with `cl100k_base` fallback) to enforce per-stage input token limits (`supervisor: 1,200`, `intake_agent: 3,400`, `evidence_analyst: 3,400`, `policy_analyst: 4,400`, `risk_anomaly_agent: 3,600`, `repair_estimate_analyst: 3,400`, `review_report: 3,800`) with a `10%` safety margin, allocating mandatory passages first. | [`token_budget_manager.py`](backend/src/claimsage/agents/token_budget_manager.py) |

### Citation Verification and Source Provenance
In insurance claims processing, every analytical statement must trace back to a specific document, page number, and passage. ClaimSage enforces provenance at three levels:
1. **Ingestion Identity**: Every chunk records its `document_id`, `filename`, `page_number`, `chunk_index`, and deterministic SHA-256 `chunk_id`.
2. **Runtime Quote Verification**: `quote_matches_evidence()` in `llm.py` verifies that quotes returned by the `PolicyAnalyst`, `RiskAnomalyAgent`, and `ReviewReportAgent` match the retrieved chunk text verbatim (normalizing typographic quotes/dashes and validating ordered ellipsis segments).
3. **Relational Provenance Links**: `_add_relational_references()` in `investigation_persistence.py` resolves cited UUIDs and 64-character SHA-256 chunk hashes back to `ClaimEvidenceChunk`, `PolicyChunk`, and `PolicyClause` database rows (`investigation_finding_references`), marking any unknown identifier as `source_kind="unresolved"` rather than fabricating metadata.

---

## 8. LangGraph Multi-Agent Architecture

```mermaid
flowchart TD
    StartNode([START])
    Investigate["1. investigate\nAuthorize Claim + Retrieve Applicable Policy Chunks\n+ Resolve Motor Repair Estimate Doc ID"]
    RetrieveEv["2. retrieve_claim_evidence\nRetrieve & Deduplicate Claim Evidence Chunks\n(pgvector Cosine Similarity)"]
    Supervisor["3. supervisor (Supervisor Agent)\nCreate SupervisorPlan (selected_analysts)\nFallback: Select All Available Analysts"]
    RouteSup{"route_after_supervisor\n(result is None?)"}

    subgraph Specialists ["Sequential Conditional Specialist Pipeline (Shared InvestigationState)"]
        Intake["4. intake_agent\nExtract Document Fields, Quality Flags\n& Document Inventory"]
        Evidence["5. evidence_analyst\nExtract Factual Findings, Timeline,\nInconsistencies & Evidence Gaps"]
        Policy["6. policy_analyst\nAnalyze Clauses, Coverage Indicators,\nSub-Limits, Exclusions & Verbatim Quotes"]
        Repair["7. repair_estimate_analyst\n(Motor Claims Only w/ Estimate Doc)\nLLM Line-Item Extraction + Decimal Rules"]
        Risk["8. risk_anomaly_agent\nCross-Source Inconsistency Check,\nHypotheses & Guardrail Validation"]
    end

    ReviewReport["9. review_report (Review & Report Agent)\nCross-Specialist Evidence Reconciliation +\nValidated Report Synthesis (or Deterministic Fallback)"]
    EndNode([END])

    StartNode --> Investigate --> RetrieveEv --> Supervisor --> RouteSup
    RouteSup -->|"result is None (Access/Task Error)"| EndNode
    RouteSup -->|"First Selected Specialist"| Intake
    RouteSup -.->|"If Intake Not Selected"| Evidence

    Intake -->|"route_after_intake_agent"| Evidence
    Evidence -->|"route_after_evidence_analyst"| Policy
    Policy -->|"Motor Claim w/ Estimate Selected"| Repair
    Policy -->|"Health Claim (Repair Skipped)"| Risk
    Repair -->|"route_after_repair_estimate_analyst"| Risk
    Risk --> ReviewReport
    ReviewReport --> EndNode
```

### Workflow State and Sequential Execution
The graph in [`backend/src/claimsage/agents/graph.py`](backend/src/claimsage/agents/graph.py) is compiled with `StateGraph(InvestigationState, context_schema=InvestigationContext)` and executes **sequentially** (agents do not run in parallel). Each node reads from and writes updates to the shared typed dictionary `InvestigationState` ([`state.py`](backend/src/claimsage/agents/state.py)), while the database `Session` is passed securely via LangGraph's `Runtime[InvestigationContext]` so database sessions never enter the serializable graph state. Before the final `review_report` node invokes its LLM synthesis, `reconcile_specialist_missing_in_state()` cross-checks specialist outputs so one agent does not report a document or fact as missing when another specialist has already extracted it.

### Implemented Agents & Graph Nodes Breakdown

| Node / Agent Name | Responsibility | Input (`InvestigationState`) | Output Schema & State Update | Architectural Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **`investigate` & `retrieve_claim_evidence`** *(Retrieval Nodes)* | Validate task and claim access, resolve loss-date-applicable policy chunks (`top_k=15`), auto-detect motor repair estimate documents, and retrieve claim evidence chunks (`top_k=5`). | `employee_id`, `claim_id`, `task`, `Runtime.context["session"]` | Populates `claim_facts`, `policy_evidence`, `claim_evidence`, `repair_estimate_document_id`, and initializes `result` with `human_review_required=True`. | Enforces tenant and RBAC boundaries before any LLM prompt is constructed. |
| **`supervisor`** (`supervisor.py`) | Reviews availability flags (`claim_facts_available`, `policy_evidence_available`, `available_analysts`) and selects which specialists should run. | `task` + boolean availability metadata | `SupervisorPlan` (`selected_analysts`, `routing_rationale`). If the LLM call fails, deterministically selects all available analysts (`supervisor_status="fallback"`). | Avoids running inapplicable agents (e.g., skips `repair_estimate_analyst` on health claims) while remaining fault-tolerant. |
| **`intake_agent`** (`intake_agent.py`) | Performs document intake: extracts structured fields (dates, names, policy numbers, invoice amounts), flags unreadable/incomplete pages, and builds a document inventory. | `task`, `claim_evidence` | `IntakeDocumentOutput` (`extracted_fields`, `document_flags`, `document_inventory`, `missing_information`, `overall_assessment`). | Produces a structured index of every field and document present in the claim file with exact page citations. |
| **`evidence_analyst`** (`evidence_analyst.py`) | Examines claim evidence documents to establish factual observations, chronological event timelines, internal document inconsistencies, and documentary gaps. | `task`, `claim_evidence` | `EvidenceAnalystOutput` (`factual_findings`, `timeline`, `inconsistencies`, `missing_information`, `evidence_gaps`, `overall_assessment`). | Separates objective medical/incident timeline facts from policy interpretation. |
| **`policy_analyst`** (`policy_analyst.py`) | Evaluates retrieved policy clauses against claim evidence and Evidence Analyst findings to identify applicable coverage provisions, sub-limits (such as room-rent caps), waiting periods, and exclusions. | `task`, `policy_evidence`, `claim_evidence`, `evidence_analysis` | `PolicyAnalystOutput` (`relevant_clauses`, `coverage_indicators`, `exclusions_and_conditions`, `missing_information`, `evidence_gaps`) with verified verbatim `supporting_quotes`. | Prevents policy hallucinations by requiring every coverage or exclusion statement to include a verbatim quote from the active policy version. |
| **`repair_estimate_analyst`** (`repair_estimate_analyst.py`) | *(Motor claims only)* Extracts repair estimate line items via LLM and runs deterministic `Decimal` arithmetic (`repair_estimate_rules.py`) to verify part/labor totals, depreciation, deductibles, and duplicate items. | `task`, all ordered chunks of `repair_estimate_document_id` | `RepairEstimateAnalystOutput` (`line_items`, deterministic `calculation`, `findings`, `clarification_questions`). Skipped automatically for health claims. | Pairs LLM line-item extraction with deterministic Python `Decimal` math to guarantee accurate total reconciliation. |
| **`risk_anomaly_agent`** (`risk_anomaly_agent.py`) | Cross-compares sanitized claim facts, retrieved evidence, and completed specialist outputs to flag cross-document inconsistencies, hypotheses requiring verification, and information gaps. | `task`, minimal `claim_facts` (`claim_type`, `status`, `loss_date`), combined evidence, `completed_analyst_outputs` | `RiskAnomalyOutput` (`observed_facts`, `anomalies`, `hypotheses`, `missing_information`). Enforces verbatim quotes and blocks prohibited fraud/decision language. | Surfaces cross-document discrepancies (e.g., billing vs. clinical dates) using cautious, non-accusatory language. |
| **`review_report`** (`review_report_agent.py`) | Reconciles missing-information items across specialists (`reconcile_specialist_missing_in_state`) and synthesizes all completed analyses into the final structured investigation report. | `ReviewReportInput` (all completed specialist outputs, retrieved evidence, uploaded document inventory) | `ReviewReportOutput` (`observed_facts`, `analyst_interpretations`, `hypotheses`, `conflicting_findings`, `missing_information`, `specialist_coverage`, `source_inventory`), or `build_fallback_partial_report` on provider failure. | Produces a single cohesive, citation-verified report for the human reviewer and guarantees partial results are preserved even if the final LLM call fails. |

---

## 9. LangChain vs LangGraph vs RAG

A clear architectural distinction exists between **RAG**, **LangChain**, and **LangGraph**, and each plays a specific role in ClaimSage:

| Concept | Architectural Role | Implementation in ClaimSage |
| :--- | :--- | :--- |
| **RAG (Retrieval-Augmented Generation)** | An **architectural pattern** in which an application retrieves relevant external documents at query time and injects them into the LLM prompt so outputs are grounded in verifiable source data. | **Custom-built in Python + SQLAlchemy (`backend/src/claimsage/rag/`)**. ClaimSage does **not** use LangChain for PDF loading, chunking, embeddings, or vector retrieval. Instead, it uses `pypdf` + PyMuPDF/Tesseract for extraction, custom page-bounded chunking (`1,000` chars / `150` overlap), `sentence-transformers/all-MiniLM-L6-v2` for 384-dim embeddings, direct SQLAlchemy `pgvector` `cosine_distance` queries with RBAC filters, and `TokenBudgetManager`. |
| **LangChain** | A **library of integrations and abstractions** (model wrappers, output parsers, callback handlers, prompt templates) for interacting with LLMs. | **Minimal, targeted usage (`backend/src/claimsage/agents/llm.py`)**. ClaimSage imports `ChatGroq` from `langchain_groq` (for primary Groq structured output via `.with_structured_output()`) and `BaseCallbackHandler` / `LLMResult` from `langchain_core` (to capture actual prompt/completion token usage). The Google Gemini fallback (`GeminiChatModel`) uses the official `google-genai` SDK directly rather than LangChain. |
| **LangGraph** | A **stateful workflow orchestration framework** built on directed graphs (`StateGraph`, nodes, conditional edges, streaming state updates) for coordinating multi-step and multi-agent execution. | **Core multi-agent orchestrator (`backend/src/claimsage/agents/graph.py`)**. ClaimSage uses LangGraph's `StateGraph(InvestigationState, context_schema=InvestigationContext)` to wire the 9 investigation nodes, evaluate conditional routing after the Supervisor and each specialist, stream per-node progress snapshots to the PostgreSQL worker, and support mid-workflow resumption. |

> [!NOTE]
> **Orchestration Rationale — Why use LangGraph instead of a linear pipeline or basic LangChain chain?**
> In a claim investigation, not every specialist applies to every claim (for example, `repair_estimate_analyst` applies only to motor claims with an uploaded estimate, and `policy_analyst` depends on whether an applicable policy version exists). Furthermore, individual cloud LLM stages can fail or encounter rate limits mid-run. **LangGraph** provides explicit typed state (`InvestigationState`), conditional edge routing (`route_after_*`), and per-node state streaming (`graph.stream(..., stream_mode="updates")`), allowing the background worker to checkpoint progress to PostgreSQL after every specialist node and resume or degrade gracefully without losing earlier completed analyses.

---

## 10. Human-in-the-Loop and Responsible AI

ClaimSage is built around a strict operational boundary: **AI assists with evidence gathering and structured analysis, while authorized humans retain exclusive authority over consequential decisions.**

```mermaid
flowchart TD
    subgraph AIZone ["AI Investigation Zone (Automated & Guardrailed)"]
        Docs["Authorized Claim Evidence & Policy Clauses"]
        Specialists["LangGraph Specialist Agents\n(Intake, Evidence, Policy, Estimate, Risk)"]
        Guardrails["Deterministic Safety Guardrails\n1. Verbatim Quote Check (quote_matches_evidence)\n2. Prohibited Decision Filter (_PROHIBITED_DECISION_PATTERNS)\n3. Mandatory Flag (human_review_required = True)"]
        Persisted["Immutable AI Findings & Report\n(investigation_findings + investigation_reports)"]

        Docs --> Specialists --> Guardrails --> Persisted
    end

    subgraph AdjusterZone ["Claims Adjuster Workspace (CLAIMS_ADJUSTER)"]
        Inspect["Inspect Report, Citations & Clauses"]
        EditFinding["Propose Versioned Finding Edit\n(POST /findings/{id}/edits)\nOriginal AI Finding Remains Immutable"]
        TryReview["Attempt Final Review Submission\n(POST /investigations/{id}/reviews)"]
        Block403["Blocked Server-Side: 403 Forbidden\n(Adjusters Cannot Approve/Finalize Reviews)"]

        Persisted --> Inspect
        Inspect --> EditFinding
        Inspect --> TryReview --> Block403
    end

    subgraph ReviewerZone ["Authorized Human Reviewer Boundary (ADMIN)"]
        AdminReview["Submit Authoritative Human Review\n(POST /api/v1/agent/investigations/{id}/reviews)"]
        DecisionRoute{"Human Decision"}
        Approve["approved\n(Investigation Review Approved)"]
        NeedDocs["needs_additional_documents\n(Generates Draft Customer Email in Sandbox Outbox)"]
        ReturnInv["returned_for_investigation\n(Re-Queues Run for Worker Analysis)"]
        Escalate["escalated / reviewed / needs_follow_up\n(Recorded with Mandatory Rationale)"]
        Audit["Immutable Audit Event Recorded\n(audit_events)"]

        Persisted --> AdminReview --> DecisionRoute
        DecisionRoute --> Approve --> Audit
        DecisionRoute --> NeedDocs --> Audit
        DecisionRoute --> ReturnInv --> Audit
        DecisionRoute --> Escalate --> Audit
    end
```

### Responsible AI Safeguards Enforced in Code
1. **No Autonomous Claim Approval or Denial**: Every specialist schema and `ReviewReportOutput` enforces `human_review_required = True`. In [`graph.py`](backend/src/claimsage/agents/graph.py), if `report.human_review_required is not True`, `run_review_report` raises `ReviewReportAgentError`.
2. **Lexical Guardrails Against Prohibited Conclusions**: [`risk_anomaly_agent.py`](backend/src/claimsage/agents/risk_anomaly_agent.py) and [`report_validation.py`](backend/src/claimsage/agents/report_validation.py) scan generated statements against `_PROHIBITED_DECISION_PATTERNS` and reject outputs containing words or phrases such as `"fraud"`, `"staged"`, `"fabricated"`, `"approve claim"`, `"deny claim"`, `"is covered"`, `"not covered"`, or `"is liable"`.
3. **Immutable AI Findings & Auditable Human Edits**: When an employee edits a finding (`create_finding_edit` in [`human_review.py`](backend/src/claimsage/services/human_review.py)), `investigation_findings.finding_data` is never overwritten. Instead, a new row is appended to `investigation_finding_edits` storing `original_data`, `edited_data`, `editor_employee_id`, and `reason`, alongside an `AuditEvent`.
4. **Role-Gated Final Review Decisions**: In [`human_review.py`](backend/src/claimsage/services/human_review.py), `record_human_review()` checks `employee.role in ALLOWED_REVIEWER_ROLES` (`{EmployeeRole.ADMIN}`). If a `CLAIMS_ADJUSTER` calls `POST /api/v1/agent/investigations/{id}/reviews`, the backend rejects the request with `HTTP 403 Forbidden`.

---

## 11. Security and Data Protection

| Security Control | Implementation Details |
| :--- | :--- |
| **JWT Authentication & Argon2id Hashing** | Passwords are hashed using **Argon2id** (`pwdlib[argon2]`). Authenticated sessions use `HS256` JWT bearer tokens (`PyJWT`) signed with a secret key validated to be at least 32 characters (`JWT_SECRET_KEY`). In the React SPA (`api-client.ts`), the access token is held in module memory rather than persisted in `localStorage`. |
| **Role-Based Access Control (RBAC)** | Enforced server-side via FastAPI dependencies and service-layer checks across `CLAIMS_ADJUSTER`, `POLICY_SPECIALIST`, `TEAM_LEAD`, and `ADMIN`. |
| **Claim-Scoped & Team-Scoped Authorization** | `get_authorized_claim()` (`claim_access.py`) verifies that a `CLAIMS_ADJUSTER` can access only claims assigned to them or their `team_id`, returning `404 Not Found` for unauthorized or non-existent claim UUIDs to prevent ID enumeration. |
| **Evidence & Policy Access Restrictions** | Claim evidence queries (`search_claim_evidence`) filter by `ClaimEvidenceDocument.claim_id == claim_id` in SQL. Policy clause reads (`GET /api/v1/policies/{id}/clauses`) verify policy document access (`user_can_access_policy_document`) before returning clauses, while policy modification and clause verification (`PATCH .../verification`) require `ADMIN` or `POLICY_SPECIALIST`. |
| **Prompt Injection & Untrusted Document Defense** | All specialist system prompts explicitly instruct the model to treat uploaded document text, claim facts, and prior analyst outputs as untrusted data, never as executable instructions. Minimal claim context (`_minimal_claim_context`) strips claimant names and narrative text before calling the Risk & Anomaly and Review Report prompts. |
| **LLM Schema & Fallback Safeguards** | Every LLM response is validated against a strict Pydantic v2 model (`extra="forbid"`). When failing over to Google Gemini, `_sanitize_gemini_json_schema()` strips `additionalProperties` from the outgoing JSON schema so Gemini accepts the request, then re-validates the returned JSON through the strict Pydantic model. Provider errors are mapped to bounded categories (`provider_failure_category`) so raw upstream error payloads or API keys never leak into state or logs. |
| **Immutable Audit Logging** | Security-relevant actions (login success/failure, claim views, document uploads/downloads, investigation runs, finding edits, human reviews) are written to `audit_events` with `CorrelationIdMiddleware` request tracing. |
| **Email Sandbox Mode & Synthetic Data** | `EMAIL_BACKEND=sandbox` prevents accidental external email transmission during development or demos. All demo claims, policyholders (e.g., *Rohan Varma*), and policies (`DEMO-HEALTH-SECURE-2026-V3`) are 100% synthetic. |

---

## 12. Project Screenshots

No standalone application UI screenshots are currently committed to the repository (only the landing-page illustration asset at [`frontend/src/assets/hero.png`](frontend/src/assets/hero.png) and framework icons are present in version control).

### Planned Screenshot Gallery
To populate a visual gallery in this section, capture the following views from `http://localhost:8080` and save them under `docs/screenshots/`:

1. `docs/screenshots/01-dashboard.png` — **Employee Dashboard (`/dashboard`)** showing active claims metrics, quick actions, and recent audit activity.
2. `docs/screenshots/02-claim-workspace.png` — **Claim Details (`/claims/7797d65d-23e2-4705-8d3a-4036244d77e3`)** showing synthetic health claim `CLM-DEMO-HEALTH-001` (*Rohan Varma*), linked policy `DEMO-HEALTH-SECURE-2026-V3`, and uploaded PDF evidence.
3. `docs/screenshots/03-investigation-report.png` — **Investigation Report (`/investigations/28e9d1ee-e7a4-4b9b-a5de-0ac0b82e88fb`)** showing the mandatory human-review banner, specialist coverage status, observed facts, and verbatim source citations.
4. `docs/screenshots/04-policy-clauses.png` — **Health Policy Document & Clauses Tab (`/policies/6b9da497-4411-4467-872a-3316e2a7350f`)** showing the 13 extracted policy clauses, 8 coverages, and 10 exclusions.
5. `docs/screenshots/05-email-sandbox.png` — **Email Follow-ups Sandbox (`/email-follow-ups`)** showing the *Safe Sandbox Active* banner and sandboxed notification records.

---

## 13. Project Structure

```text
ClaimSage-v2-clean/
|-- .env.example                        # Safe environment variable template (no real secrets)
|-- CONTRIBUTING.md                     # Developer contribution & pull request guidelines
|-- docker-compose.yml                  # 6-service Docker orchestration (db, minio, migrate, backend, worker, frontend)
|-- README.md                           # Root project documentation
|-- backend/
|   |-- Dockerfile                      # Python 3.12 container image for backend, migrate & worker
|   |-- pyproject.toml                  # Python dependencies, Ruff linter & Pytest configuration
|   |-- alembic.ini                     # Alembic database migration configuration
|   |-- scripts/                        # Operational & demo seeding scripts (seed_demo.py, set_demo_passwords.py, run_investigation_worker.py)
|   |-- src/claimsage/
|   |   |-- main.py                     # FastAPI app initialization, middleware & /health endpoints
|   |   |-- agents/                     # LangGraph workflow (graph.py, state.py), 6 specialists, LLM failover (llm.py) & TokenBudgetManager
|   |   |-- api/routes/                 # FastAPI REST routers (auth, claims, evidence, policies, agent, investigations, customer_emails, audit, system)
|   |   |-- core/                       # Settings (config.py), correlation-ID observability, rate limiting & upload limits
|   |   |-- db/                         # SQLAlchemy 2.0 ORM models (21 tables in models.py) & session factory
|   |   |-- rag/                        # PDF extraction (document_loader.py), OCR (ocr_service.py), embeddings (embedding_service.py) & two-pass retrieval
|   |   |-- schemas/                    # Pydantic v2 request/response contracts
|   |   |-- services/                   # Domain services (auth, claim/document RBAC, persistence, human_review, notifications, MinIO storage, audit)
|   |   |-- tools/                      # Authorized claim lookup tool (claim_tools.py)
|   |   +-- workers/                    # Durable PostgreSQL worker (investigation_worker.py) with SKIP LOCKED leases & heartbeats
|   +-- tests/                          # Automated backend test suite (814 tests)
|-- frontend/
|   |-- Dockerfile                      # Multi-stage Node build + Nginx 1.27 Alpine runtime image
|   |-- nginx.conf                      # SPA routing & /api + /health reverse-proxy configuration
|   |-- package.json                    # React 19, TypeScript 5.9, Vite 8, Tailwind v4 & TanStack Query dependencies
|   +-- src/
|       |-- app/                        # Authenticated application shell & layout
|       |-- components/                 # Reusable UI primitives & navigation sidebar
|       |-- features/                   # Domain modules (landing, auth, dashboard, claims, investigations, policies, documents, communications, audit, settings)
|       |-- lib/                        # Axios API client (in-memory JWT) & React Query client
|       +-- types/                      # TypeScript interfaces matching backend Pydantic schemas
+-- docs/
    |-- ARCHITECTURE.md                 # Detailed system & database architecture blueprint
    |-- AGENT_WORKFLOW.md               # Specialist agent contracts & LangGraph routing guide
    |-- API_GUIDE.md                    # REST endpoint reference
    |-- DEMO_GUIDE.md                   # Step-by-step live demonstration script
    |-- PROJECT_REPORT.md               # Comprehensive project engineering report
    |-- SECURITY.md                     # Threat model, RBAC matrix & security controls
    |-- TESTING.md                      # Test suite execution & verification guide
    +-- policies/                       # Synthetic Health (v3) and Motor (v1) PDF policy documents
```

---

## 14. Installation and Local Setup

The instructions below are verified for **Windows (PowerShell)** using Docker Desktop.

### Prerequisites
- **Docker Desktop** (with Docker Compose v2 enabled and running)
- **Git**
- *(Optional for host-level development/testing)* **Python 3.12** and **Node.js 20+**
- Your own **Groq API Key** (`GROQ_API_KEY`) and optional **Google Gemini API Key** (`GEMINI_API_KEY`) for live cloud LLM generation

### 1. Clone the Repository
```powershell
git clone https://github.com/Sumeet2005/ClaimSage-v2.git
cd ClaimSage-v2
```

### 2. Configure Environment Variables
Copy the template `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Open `.env` in your editor and configure your local credentials (never commit `.env` to Git):
- `GROQ_API_KEY`: Set your Groq Cloud API key (used by primary model `openai/gpt-oss-120b`).
- `GEMINI_API_KEY`: *(Optional)* Set your Google AI Studio API key (used by secondary fallback model `gemini-3.8-flash`).
- `JWT_SECRET_KEY`: Set a random secret string of at least 32 characters for `HS256` JWT signing.
- `POSTGRES_PASSWORD` and `STORAGE_SECRET_KEY`: Keep or customize your local PostgreSQL and MinIO passwords.
- `EMAIL_BACKEND`: Leave as `sandbox` so all emails remain safely inside the local outbox.

### 3. Start the Application Stack with Docker Compose
Start all services (`db`, `minio`, `migrate`, `backend`, `worker`, `frontend`) in detached mode:
```powershell
docker compose -p claimsage up -d --build
```
Check that all containers are running and healthy:
```powershell
docker compose -p claimsage ps
```

### 4. Seed Demo Data & Set Interactive Demo Passwords (First-Time Setup Only)
If starting from an empty database volume, seed the synthetic claims, policies, embeddings, and demo accounts:
```powershell
docker exec -it claimsage-backend python scripts/seed_demo.py
docker exec -it claimsage-backend python scripts/seed_phase9_demo_claims.py
docker exec -it claimsage-backend python scripts/register_new_synthetic_policies.py
docker exec -it claimsage-backend python scripts/embed_pending_chunks.py
```
Because ClaimSage never hardcodes plaintext employee passwords in source code, set your local demo passwords interactively (stored as one-way Argon2id hashes in `employees.password_hash`):
```powershell
docker exec -it claimsage-backend python scripts/set_demo_passwords.py
```

### 5. Access URLs & Health Checks
- **Frontend Web Application**: `http://localhost:8080`
- **Backend Liveness Probe**: `http://localhost:8080/health/live`
- **Backend Readiness Probe (DB + Queue + MinIO)**: `http://localhost:8080/health/ready`

Verify health from PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8080/health/live"
Invoke-RestMethod -Uri "http://localhost:8080/health/ready"
docker exec claimsage-worker python -u scripts/run_investigation_worker.py --check-readiness
```

### 6. Stop Services Safely
To stop containers while preserving all PostgreSQL and MinIO data volumes:
```powershell
docker compose -p claimsage down
```
> [!CAUTION]
> Do **not** pass `-v` (`docker compose down -v`) unless you intentionally want to wipe your local database and MinIO object storage volumes.

---

## 15. Demo Walkthrough

This walkthrough uses the pre-seeded **synthetic health insurance claim** verified during acceptance testing. All names, medical records, and policy numbers are fictional.

- **Demo Claim Number**: `CLM-DEMO-HEALTH-001` (UUID: `7797d65d-23e2-4705-8d3a-4036244d77e3`)
- **Synthetic Policyholder**: Rohan Varma (*3-day inpatient hospitalization for acute appendicitis / laparoscopic appendectomy*)
- **Linked Health Policy**: `DEMO-HEALTH-SECURE-2026-V3` (*Demo Health Secure Plan v3.0*, UUID: `6b9da497-4411-4467-872a-3316e2a7350f`)
- **Uploaded Evidence PDF**: `claimsage_synthetic_health_evidence_rohan_varma.pdf` (`4` extracted chunks)
- **Completed Reference Investigation**: `28e9d1ee-e7a4-4b9b-a5de-0ac0b82e88fb`
- **Demo Accounts**:
  - Claims Adjuster: `alex.adjuster@claimsage.local`
  - Administrator: `admin@claimsage.local`

### Step-by-Step Walkthrough

1. **Login (`/login`)**: Sign in at `http://localhost:8080/login` as Claims Adjuster `alex.adjuster@claimsage.local` using the password configured via `set_demo_passwords.py`.
2. **Dashboard (`/dashboard`)**: Inspect the employee role badge (*Alex Morgan — Claims Adjuster*), active claim metrics, quick navigation cards, and live audit activity feed.
3. **Claims Workspace (`/claims`)**: View the claims table containing the 5 synthetic health and motor claims (`CLM-DEMO-HEALTH-001` through `003` and `CLM-DEMO-MOTOR-001` through `002`) with status and policy badges.
4. **Claim Details (`CLM-DEMO-HEALTH-001`)**: Open `CLM-DEMO-HEALTH-001` to inspect the structured claim header (`status: under_review`, linked policy `DEMO-HEALTH-SECURE-2026-V3`, loss date, and claim narrative).
5. **Evidence Document (`/documents`)**: Locate the uploaded PDF `claimsage_synthetic_health_evidence_rohan_varma.pdf` (`Storage Ready` in MinIO, `4` embedded chunks) and click **Download** to verify SHA-256-checked PDF streaming from MinIO.
6. **Investigation Workspace (`/investigations/28e9d1ee-e7a4-4b9b-a5de-0ac0b82e88fb`)**: Open the completed investigation from the claim page to view overall status (`completed`), the **Human Review Required** governance banner, and the `90` persisted findings.
7. **Specialist Analysis Tabs**: Review the specialist coverage breakdown (`intake_agent`, `evidence_analyst`, `policy_analyst`, and `risk_anomaly_agent` all `completed`; `repair_estimate_analyst` automatically `skipped` because this is a health claim).
8. **RAG & Evidence Citations**: Inspect individual findings under **Risk Analysis** (`12` findings) and **Evidence Analysis** (`17` findings) to see how extracted facts (such as the 3-day admission and INR 4,500/day general ward accommodation charge) cite exact chunk IDs, page numbers, and verbatim quotes from `claimsage_synthetic_health_evidence_rohan_varma.pdf`.
9. **Policy Analysis & Clauses (`DEMO-HEALTH-SECURE-2026-V3`)**: Inspect the **Policy Analysis** section (`19` findings comparing the claim against Section 3 Inpatient Hospitalization Coverage and the INR 5,000/day normal room-rent sub-limit), then navigate to **Policies** $\rightarrow$ `DEMO-HEALTH-SECURE-2026-V3` $\rightarrow$ **Document & Clauses** tab to view all `13` extracted clauses, `8` coverages, and `10` exclusions. As a Claims Adjuster, all clauses are readable (`HTTP 200`), while the **Verify Clause** administrative action is hidden and blocked server-side (`HTTP 403`).
10. **Synthesized Investigation Report**: Return to the investigation's **Report** section to inspect the validated `ReviewReportOutput`: `4` observed facts, `3` analyst interpretations, `1` hypothesis, `9` missing-information items, and the `2`-document source inventory.
11. **Human Review Controls (`/review-queue`)**: Open the Review Queue to observe the role boundary: Adjusters can inspect reports and record versioned finding edits (with immutable original AI data), while submitting a final review decision (`POST /api/v1/agent/investigations/{id}/reviews`) is restricted to `ADMIN` (`admin@claimsage.local`).
12. **Email Sandbox (`/email-follow-ups`)**: Open **Email Follow-ups** to inspect the **Safe Sandbox Active** banner and the `2` `sandboxed` notification delivery records generated for `CLM-DEMO-HEALTH-001`.

---

## 16. Testing and Verification

The results below summarize the **previously reported verification results** recorded in [`docs/TESTING.md`](docs/TESTING.md) and [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md) (executed against the isolated `claimsage_test` PostgreSQL database and live local Docker stack):

### Reported Verification Summary (`2026-11-15`)
| Verification Area | Reported Result | Details |
| :--- | :--- | :--- |
| **Full Backend Test Suite (`pytest backend/tests -q`)** | **814 passed, 0 failed, 0 skipped** | Executed across authentication, RBAC, PDF ingestion, OCR, embeddings, contextual RAG, LangGraph routing, worker leasing, LLM failover, human review, and audit logging (`23,375.36s`). |
| **Targeted Acceptance Suite** | **52 passed, 0 failed** | Fast verification subsuite (`22.92s`) covering Policy Clauses RBAC (`BUG-03`), Finding Reference resolution (`BUG-04`), Gemini schema sanitization (`BUG-02`), and contextual RAG token budgets. |
| **Remediation & RAG/RBAC Subsuites** | **106 passed** (`3.99s`) / **164 passed** (`27.69s`) | Targeted unit, PostgreSQL persistence, citation provenance, and cross-role authorization suites. |
| **Frontend Typecheck (`npm run typecheck`)** | **Passed (`0 errors`)** | `tsc -b` across all TypeScript files. |
| **Frontend Lint (`npm run lint`)** | **Passed (`0 errors, 0 warnings`)** | `eslint .` static analysis. |
| **Frontend Production Build (`npm run build`)** | **Passed (`1.73s`)** | `2,748` modules transformed into `frontend/dist/` (`0` secret leaks in 64 JS bundles). |
| **Automated Browser Acceptance (`http://localhost:8080`)** | **18 / 18 views + Logout passed** | Verified Login, Dashboard, Claims List, Claim Details, Investigation Details, Report, Specialist Coverage, Risk Analysis, Policy Analysis, Review Queue, Email Follow-ups, Documents, Document Download, Policies, Health Policy Details, Document & Clauses Tab, Exclusions Tab, Linked Claims Tab, and Logout with `0` console/network errors. |
| **Docker Services Health** | **All services reported healthy** | `claimsage-db` (`Up (healthy)`), `claimsage-minio` (`Up (healthy)`), `claimsage-backend` (`Up (healthy)`), `claimsage-worker` (`Up (healthy)`), `claimsage-frontend` (`Up`). |

### Commands to Run Tests Locally

**Run Fast Targeted Backend Verification Suite (~25 seconds):**
```powershell
$env:CLAIMSAGE_DISABLE_DOTENV="1"
$env:APP_ENV="test"
$env:DATABASE_URL="postgresql+psycopg://claimsage_app:change-this-local-password@127.0.0.1:5432/claimsage_test"
$env:JWT_SECRET_KEY="test-secret-key-at-least-32-chars-long-for-pytest"
$env:GROQ_API_KEY="gsk_test_dummy_key_for_unit_tests_only"
.\.venv\Scripts\pytest.exe backend/tests/test_investigation_persistence.py backend/tests/test_llm.py backend/tests/test_policy_clause_review.py backend/tests/test_contextual_retrieval_and_token_budget.py -q
```

**Run Frontend Checks:**
```powershell
cd frontend
npm run typecheck
npm run lint
npm run build
```

---

## 17. Known Limitations

The following operational and architectural boundaries apply to the current implementation:

### 1. External LLM Provider & Free-Tier Rate Limits
- **Groq Free-Tier TPM Quotas**: Free-tier Groq Cloud accounts enforce strict rolling tokens-per-minute limits. To prevent mid-investigation `429 Too Many Requests` failures, `graph.py` applies a configurable pacing delay (`GROQ_PACING_DELAY_SECONDS=16.0` in `.env.example`, or 20–28s stage defaults in `_apply_pacing_delay`) between cloud specialist calls outside `APP_ENV=test`.
- **Google Gemini Preview Capacity Spikes**: While `ReviewReportExtraction` and all specialist schemas are 100% compatible with the Google GenAI SDK (`_sanitize_gemini_json_schema`), the configured `gemini-3.8-flash` preview model on Google AI Studio Free Tier can experience upstream `503 UNAVAILABLE` or `504 DEADLINE_EXCEEDED` spikes under high demand. When both Groq and Gemini fail on the report stage, ClaimSage degrades gracefully to `build_fallback_partial_report`.

### 2. Retrieval & Document Scope Limitations
- **Dense Cosine Similarity Only**: Vector search uses exact SQL `cosine_distance` over `Vector(384)` embeddings without sparse BM25/`tsvector` hybrid fusion or approximate HNSW indexing (which is fast and exact at current dataset scale but would require indexing for millions of chunks).
- **Page-Bounded PDF Text/OCR Only**: Ingestion supports unencrypted `.pdf` files up to 20 MiB. Handwritten notes with poor scan quality may still yield low OCR confidence, which the Intake Agent flags for human review rather than guessing.

### 3. Demo & Operational Scope
- **Interactive Demo Password Setup**: Seeded demo accounts (`alex.adjuster@claimsage.local`, `admin@claimsage.local`) require running `scripts/set_demo_passwords.py` to set a known local password hash rather than shipping plaintext credentials in the repository.
- **Seeded Live Database Roles**: The default seeded `claimsage` database includes `ADMIN` and `CLAIMS_ADJUSTER` accounts; `POLICY_SPECIALIST` and `TEAM_LEAD` workflows are verified through the automated `pytest` RBAC suites in `claimsage_test` unless additional demo users are provisioned.
- **Historical Finding Reference Rows**: In the pre-seeded reference investigation (`28e9d1ee-e7a4-4b9b-a5de-0ac0b82e88fb`), `62` historical rows in `investigation_finding_references` created prior to the `BUG-04` fix remain marked `"unresolved"` in the relational link table because historical database records were intentionally not rewritten (the investigation's JSONB report and finding citations remain complete, and all newly persisted runs resolve both UUID and SHA-256 chunk IDs).
- **Email Sandbox Mode**: Outbound emails default to `EMAIL_BACKEND=sandbox` and are stored in `customer_emails` / `notification_deliveries` rather than being delivered over live SMTP unless an SMTP server is explicitly configured.

---

## 18. Future Improvements

The following enhancements are planned next steps and are **not** claimed as currently implemented:

1. **Hybrid Dense + Sparse Search with HNSW Indexing**: Add PostgreSQL `pgvector` HNSW indexes and combine dense `all-MiniLM-L6-v2` cosine similarity with PostgreSQL `tsvector` full-text search using Reciprocal Rank Fusion (RRF) for exact medical billing code and ICD-10 keyword matching.
2. **Real-Time Server-Sent Events (SSE) / WebSockets**: Replace HTTP polling on the investigation progress view with SSE or WebSocket push notifications as each LangGraph node completes.
3. **Cross-Encoder Reranking**: Introduce a lightweight local cross-encoder reranker between Pass 2 candidate recall and `TokenBudgetManager` selection.
4. **Side-by-Side PDF Viewer with Highlighted Bounding Boxes**: Render the original PDF from MinIO directly inside the React investigation workspace and highlight the cited page and paragraph when an adjuster clicks a finding reference.
5. **OpenTelemetry Distributed Tracing**: Export correlation IDs, LangGraph node spans, and `UsageCaptureCallbackHandler` token metrics to an OpenTelemetry collector (e.g., Jaeger / Grafana Tempo).

---

## 19. Author & Supporting Documentation

- **Author**: Sumeet (`@Sumeet2005`)
- **Project**: ClaimSage — AI Insurance Employee Assistant
- **Repository**: [https://github.com/Sumeet2005/ClaimSage-v2](https://github.com/Sumeet2005/ClaimSage-v2)
- **Supporting Documentation**:
  - [System Architecture (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)
  - [Multi-Agent Workflow (`docs/AGENT_WORKFLOW.md`)](docs/AGENT_WORKFLOW.md)
  - [API Guide (`docs/API_GUIDE.md`)](docs/API_GUIDE.md)
  - [Security & RBAC (`docs/SECURITY.md`)](docs/SECURITY.md)
  - [Testing Guide (`docs/TESTING.md`)](docs/TESTING.md)
  - [Demo Guide (`docs/DEMO_GUIDE.md`)](docs/DEMO_GUIDE.md)
  - [Project Report (`docs/PROJECT_REPORT.md`)](docs/PROJECT_REPORT.md)
  - [Document Retention & Recovery Policy (`docs/document_retention_and_recovery_policy.md`)](docs/document_retention_and_recovery_policy.md)
