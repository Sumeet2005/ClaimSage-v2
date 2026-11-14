# ClaimSage — Demonstration & Employee Workflow Guide

This guide walks through demonstrating ClaimSage to stakeholders, reviewing claim evidence, exploring AI investigation findings, and walking through the human review queue.

---

## 1. Starting the Application

Ensure the Docker environment is running:

```powershell
docker compose -p claimsage up -d
```

Verify that all five containers report healthy status:

```powershell
docker compose -p claimsage ps
```

The web application is accessible at:
- **Frontend Portal**: `http://localhost:8080`
- **Backend Health Check**: `http://localhost:8080/health/ready`
- **Interactive OpenAPI Documentation**: `http://localhost:8080/docs`

---

## 2. Demo User Accounts

ClaimSage provides pre-configured role-based synthetic user accounts:

| Role | Email | Scope of Access | Password Setup |
| :--- | :--- | :--- | :--- |
| **Claims Adjuster** | `alex.adjuster@claimsage.local` | Property and assigned team claims | Configured during initial seeding |
| **Motor Adjuster** | `taylor.adjuster@claimsage.local` | Motor and vehicle damage claims | Configured during initial seeding |
| **Team Lead / Supervisor**| `jordan.lead@claimsage.local` | Team claims, review queue, escalations | Configured during initial seeding |
| **Policy Specialist** | `casey.policy@claimsage.local` | Policy knowledge base, clause verifications | Configured during initial seeding |
| **Administrator** | `admin@claimsage.local` | Full platform visibility, audit logs, all claims | Configured during initial seeding |

> [!NOTE]
> To reset or configure demo account passwords locally, an authorized administrator can run:
> ```powershell
> python backend/scripts/set_demo_passwords.py
> ```
> Passwords must be at least 12 characters long (e.g. `DemoAdjuster2026!`).

---

## 3. Walking Through the Reference Health Claim

### Step A: Sign In
1. Open `http://localhost:8080` in your browser.
2. If at the landing page, click **Sign In** or **Launch Workspace**.
3. Sign in as an adjuster (e.g. `alex.adjuster@claimsage.local`) or administrator (`admin@claimsage.local`).

### Step B: Open the Reference Claim
1. In the sidebar, navigate to **Claims**.
2. Select **`CLM-DEMO-HEALTH-001`** (*Claimant: Rohan Varma*).
3. Review the claim metadata card:
   - **Claim Type**: Health
   - **Policy**: `DEMO-HEALTH-SECURE-2026-V3`
   - **Status**: `under_review`

### Step C: Inspect Uploaded Evidence & Ingestion
1. Under the **Evidence** section or by visiting **Documents** in the sidebar:
   - Review the indexed files:
     - *Hospital Itemized Bill & Receipts* (`.pdf`)
     - *Inpatient Discharge Summary* (`.pdf`)
     - *Physician Prescription & Diagnostic Reports* (`.pdf`)
   - Notice the extracted passage chunk counts and storage status (`stored`, SHA-256 verified).
   - Click the **Download** button to test secure, authenticated evidence retrieval via blob stream.

### Step D: Inspect Completed Multi-Agent Investigation
1. Under the **Investigation History** section of the claim:
   - Observe the reference completed investigation run (`f984f980-a782-4880-8a8d-c4dc19400f3e`).
   - Click **View Investigation** to open the full investigation workspace (`/investigations/f984f980-a782-4880-8a8d-c4dc19400f3e`).

### Step E: Review Specialist Diagnostics & Findings
1. Explore the individual specialist tabs:
   - **Intake Specialist**: Catalogs the document inventory, validates medical admission timestamps, and checks for missing intake forms.
   - **Evidence Analyst**: Timeline reconstruction of medical procedures, itemized billing cross-references, and supporting quotes.
   - **Policy Analyst**: Evaluates room-rent caps, intensive care sub-limits, disease-specific waiting periods, and proportional deduction rules under `DEMO-HEALTH-SECURE-2026-V3`.
   - **Risk & Anomaly Agent**: Flags potential duplicate billing entries or unbundled procedural fees.
   - **Review & Report Agent**: Synthesized executive summary, overall risk score, and recommended adjuster action items.
2. Hover over or expand individual findings to inspect **Citations & Provenance**:
   - Every finding provides direct links to the document name, page number, and verbatim excerpt.

---

## 4. Demonstrating Human Review (Without Approving/Denying Demo Claim)

> [!IMPORTANT]
> **Safety Rule**: Do not submit final claim settlement, approval, or denial decisions against the baseline demo claim `CLM-DEMO-HEALTH-001`.

To demonstrate the review capabilities safely:
1. In the sidebar, navigate to **Review Queue** (`/review-queue`).
2. Notice the claims awaiting human review:
   - The queue displays the AI preliminary risk score, policy coverage posture, and missing evidence flags.
3. Open the review interface for an investigation:
   - **Findings Editing**: Demonstrate how an adjuster can add notes or edit an AI-generated finding without altering the immutable raw AI finding record.
   - **Draft Decision Form**: Show the adjuster decision options (**Request Information**, **Escalate to Supervisor**, **Approve with Sub-limits**, **Deny Coverage**).
   - Demonstrate client-side validation (e.g. mandatory rationale field requirement).
   - Click **Cancel** or navigate back to preserve the unreviewed baseline state.

---

## 5. Demonstrating Sandboxed Communications & Audit Trail

### Sandboxed Customer Email Follow-ups
1. Navigate to **Customer Emails** (`/email-follow-ups`).
2. Demonstrate how AI agents draft follow-up inquiries (e.g. requesting missing diagnostic test reports or pharmacy bills).
3. Point out the safety controls:
   - The outbound transport backend is set to `EMAIL_BACKEND=sandbox`.
   - Emails are stored durably in the outbox table for adjuster inspection and cannot be dispatched to real email addresses without explicit human sign-off.

### Immutable Audit Trail
1. Navigate to **Audit Logs** (`/audit-logs`).
2. Filter by category:
   - `auth`: Sign-in events and token issuance.
   - `evidence`: Document uploads and downloads.
   - `investigation`: Worker job execution, stage progress, and heartbeat refreshes.
   - `review`: Human review actions and finding edits.
3. Show the correlation ID tracking every user action end-to-end.
