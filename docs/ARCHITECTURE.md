# ClaimSage System Architecture & Technical Specifications

This document details the architectural blueprint of ClaimSage, illustrating component relationships, data flow, container topology, and state transitions.

---

## 1. Container Topology & Network Architecture

```mermaid
flowchart TD
    Client(["Browser Client (Claims Adjuster / Supervisor)"])
    
    subgraph DockerHost ["Docker Compose Environment (claimsage-network)"]
        Nginx["claimsage-frontend\nNginx 1.27 (Alpine)\nPort :8080"]
        API["claimsage-backend\nFastAPI 0.115+ (Python 3.12)\nPort :8000"]
        Worker["claimsage-worker\nAsync Polling Worker\nLease Management"]
        DB[("claimsage-db\nPostgreSQL 16 + pgvector\nPort :5432")]
        MinIO[("claimsage-minio\nS3-Compatible Object Store\nPorts :9000/:9001")]
    end

    Client -->|HTTP :8080| Nginx
    Nginx -->|Static Assets /| Nginx
    Nginx -->|Reverse Proxy /api/ & /health/| API
    API -->|SQLAlchemy / psycopg3| DB
    API -->|boto3 S3 Client| MinIO
    Worker -->|Queue Polling & State| DB
    Worker -->|Document Chunks| MinIO
    Worker -->|Cloud LLM Invocations| CloudLLM["External LLM Providers\nGroq Cloud (Primary)\nGoogle Gemini (Fallback)"]
```

---

## 2. Asynchronous Investigation Execution Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Queued: User launches investigation via API
    Queued --> Claimed: Worker acquires lease (SKIP LOCKED)
    Claimed --> RetrievingEvidence: Hybrid RAG Query
    RetrievingEvidence --> SupervisorPlanning: Formulate Specialist Plan
    SupervisorPlanning --> IntakeSpecialist: Extract Doc Inventory
    IntakeSpecialist --> EvidenceAnalysis: Build Event Timeline
    EvidenceAnalysis --> PolicyAnalysis: Evaluate Policy Clauses
    PolicyAnalysis --> RepairEstimate: (Motor Claims Only)
    PolicyAnalysis --> RiskAnalysis: (Health Claims / Skip Repair)
    RepairEstimate --> RiskAnalysis: Evaluate Discrepancies
    RiskAnalysis --> EvidenceReconciliation: Reconcile Shared Facts
    EvidenceReconciliation --> ReviewReport: AI Synthesis / Fallback
    ReviewReport --> Completed: Persist Findings & Release Lease
    ReviewReport --> Incomplete: Rate Limit / Partial Fallback
    Completed --> [*]
    Incomplete --> [*]
```

---

## 3. Storage Layer Architecture
- **Relational Tables**: Store users, claims, versioned policies, policy clauses, investigation state, and audit logs.
- **pgvector Vector Column**: `document_chunks.embedding` and `policy_chunks.embedding` are stored as `Vector(384)` indexed with HNSW / Cosine similarity.
- **MinIO Object Storage**: Claim PDFs and policy documents are stored as raw binary objects indexed by UUID-based keys.
- **Audit Outbox**: Customer email drafts and system notifications are stored in durable relational outbox tables prior to sandboxed or SMTP dispatch.
