# ClaimSage — Enterprise Document Retention, Soft Deletion & Disaster Recovery Policy

**Document ID:** POL-CS-SEC-004  
**Classification:** Confidential — Internal Operational Policy  
**Effective Date:** November 2026  
**Scope:** Policy Documents, Claim Evidence Documents, Embeddings, and Associated Audit Trails  

---

## 1. Regulatory Context & Retention Periods

Insurance documents are subject to strict statutory preservation requirements governed by state insurance regulators, NAIC Model Guidelines, and federal privacy regulations (HIPAA for health insurance claims, Gramm-Leach-Bliley Act for financial records).

### Statutory Retention Periods
| Record Type | Retention Period | Trigger Event | Justification |
| :--- | :--- | :--- | :--- |
| **Health Policy Master Documents** | 7 Years | Expiration of policy term or product withdrawal | State Insurance Code & contractual statute of limitations. |
| **Auto/Motor Policy Documents** | 7 Years | Expiration of policy term | Regulatory compliance and third-party liability exposure. |
| **Claim Evidence Documents (Bills, Estimates, Photos)** | 7 Years post-closure | Date claim status transitions to `closed` or `settled` | Fraud investigations, reinsurance audits, dispute resolution. |
| **Investigation Findings & Agent Reports** | 7 Years post-closure | Investigation completion date | Adjudication transparency and defensibility in litigation. |
| **Audit Logs & Activity Records** | 10 Years | Event creation timestamp | Regulatory scrutiny, non-repudiation, and forensic investigation. |

---

## 2. Document Deletion Strategy

### 2.1 Soft Deletion (Tombstoning)
In production ClaimSage deployments, documents must **never** be physically deleted upon standard user or adjuster request. Instead, a soft-deletion pattern is enforced:
1. **Metadata Preservation:** The database record remains intact with flags:
   - `is_deleted`: `BOOLEAN DEFAULT FALSE`
   - `deleted_at`: `TIMESTAMPTZ NULL`
   - `deleted_by_employee_id`: `UUID NULL`
2. **Access Revocation:** Soft-deleted records are automatically filtered out from normal adjuster searches, RAG semantic retrieval vector queries, and API listings.
3. **Foreign Key Integrity:** Historical investigation findings, reports, and audit logs that reference the document retain referential integrity without broken links.
4. **Storage Retention:** The object storage payload (S3/MinIO) is retained in an archival tier or tagged with `Lifecycle=SoftDeleted` until the statutory retention period elapses.

### 2.2 Legal Holds
A **Legal Hold** supersedes all retention rules, soft-deletion schedules, and automated lifecycle purges.
* **Invariant:** When `legal_hold = TRUE`, any deletion request (soft or permanent) is rejected immediately with HTTP 409 Conflict:
  `"Document is subject to an active Legal Hold and cannot be deleted or purged."`
* **Authority:** Only the **Compliance Officer** or **Legal Counsel** role can place or release a legal hold.
* **Audit Requirement:** Placing or releasing a legal hold emits a critical severity `AuditEvent` with mandatory justification text.

### 2.3 Permanent Deletion (Purge) Authorization
Permanent physical destruction of documents (both PostgreSQL rows and S3 objects) is strictly restricted:
1. **Role Requirement:** Restricted to `Role: ComplianceAdmin` or `Role: SystemAdmin`. Adjusters, Investigators, and Supervisors have zero purge permissions.
2. **Dual-Custody Workflow:** For bulk or permanent purges, a deletion request must be initiated by one administrator and approved by a second compliance officer before execution.
3. **Retention Verification:** Automated pre-flight validation verifies that the document's statutory retention period has expired and no active legal hold exists.
4. **Permanent Audit Log:** A cryptographic hash, document metadata, and deletion confirmation are permanently preserved in the append-only `audit_events` table before object deletion.

---

## 3. Storage Versioning & Integrity Protection

### 3.1 Object Versioning
In production AWS S3 environments:
* **Bucket Versioning:** Enabled (`VersioningConfiguration={'Status': 'Enabled'}`).
* **MFA Delete:** Enabled for bucket configuration to prevent accidental or unauthorized bucket-wide deletions.
* **Object Lock:** S3 Object Lock configured in **Governance Mode** with default retention matching statutory periods (e.g., 7 years), protecting files against ransomware or accidental deletion.

### 3.2 Orphaned-Object Reconciliation
To ensure that object storage (S3/MinIO) and relational metadata (PostgreSQL) remain synchronized without leaking orphaned files:
1. **Scheduled Reconciliation Job:** A monthly non-destructive audit script scans the storage bucket and database:
   - Queries all distinct `storage_key` entries from `policy_documents` and `claim_evidence_documents`.
   - Lists all object keys in the S3 bucket.
2. **Dry-Run Audit:** Unreferenced objects are recorded in a reconciliation log (`s3_reconciliation_audit`).
3. **Quarantine Procedure:** Unreferenced objects are moved to a `quarantine/` prefix for 30 days before permanent purging, allowing recovery if a recent upload failed mid-transaction.

---

## 4. Disaster Recovery & Backup Architecture

### 4.1 PostgreSQL Backup & Recovery (RPO <= 5 min, RTO <= 1 hr)
1. **Continuous WAL Archiving:** PostgreSQL Write-Ahead Logs (WAL) are continuously archived to a dedicated, encrypted S3 bucket (`s3://claimsage-db-backups/wal/`) using `pgBackRest` or managed AWS RDS automated WAL archiving.
2. **Daily Base Backups:** Full consistent physical snapshots taken nightly at 02:00 UTC.
3. **Point-In-Time Recovery (PITR):** Enables restoration of the database to any millisecond within the preceding 35 days.
4. **Drill Schedule:** Monthly automated restoration into an isolated test environment (`claimsage_dr_test`) to verify backup integrity and restore runbooks.

### 4.2 Object Storage Disaster Recovery
1. **Cross-Region Replication (CRR):** S3 bucket replication configured to automatically copy uploaded documents to a secondary AWS region (e.g., primary `us-east-1` to disaster-recovery `us-west-2`).
2. **Lifecycle Management:**
   - Days 0–90: S3 Standard (instant retrieval for active claims).
   - Days 91–730: S3 Glacier Instant Retrieval (cost-optimized, millisecond access).
   - Year 2–7: S3 Glacier Flexible Retrieval or Deep Archive (statutory preservation).
   - Year 7+: Purge eligible after compliance review and legal hold check.

---

## 5. Production Infrastructure Requirements Checklist

The following infrastructure components are required for full production compliance:

- [ ] **AWS S3 Bucket Versioning & Object Lock:** Enabled in Governance Mode on the primary document bucket.
- [ ] **KMS Customer Managed Key (CMK):** Configured with automatic key rotation and strict IAM key policy.
- [ ] **PostgreSQL PITR:** AWS RDS Multi-AZ deployment with automated continuous backup retention (35 days).
- [ ] **Cross-Region Replication:** Asynchronous S3 replication to secondary DR region.
- [ ] **Reconciliation Cron Job:** Scheduled monthly job executing non-destructive orphaned object detection.
