"""Execute and verify Phase 3 Controlled Live Investigation for CLM-DEMO-HEALTH-001."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import create_engine, select
from claimsage.core.config import get_settings
from claimsage.db.models import (
    AuditEvent,
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
    InvestigationFinding,
    InvestigationFindingReference,
    InvestigationReport,
    InvestigationRun,
    PolicyDocument,
)
from claimsage.services.auth import create_access_token

CLAIM_NUMBER = "CLM-DEMO-HEALTH-001"
EXPECTED_POLICY = "DEMO-HEALTH-SECURE-2026-V3"


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)

    print("=== PHASE 3: CONTROLLED LIVE INVESTIGATION PRE-FLIGHT ===")
    with engine.connect() as conn:
        claim = conn.execute(
            select(Claim).where(Claim.claim_number == CLAIM_NUMBER)
        ).fetchone()

        if not claim:
            print(f"ERROR: Claim {CLAIM_NUMBER} not found.")
            return 1

        claim_id = str(claim.id)
        print(f"Claim ID: {claim_id}")
        print(f"Claim Number: {claim.claim_number}")
        print(f"Claimant: {claim.claimant_name}")
        print(f"Policy Identifier: {claim.policy_identifier}")
        print(f"Claim Type: {claim.claim_type}")
        print(f"Status: {claim.status}")

        if claim.policy_identifier != EXPECTED_POLICY:
            print(f"ERROR: Expected policy {EXPECTED_POLICY}, got {claim.policy_identifier}")
            return 1

        # Check for active running investigations
        active_runs = conn.execute(
            select(InvestigationRun).where(
                InvestigationRun.claim_id == claim.id,
                InvestigationRun.status.in_(["queued", "running"]),
            )
        ).fetchall()
        if active_runs:
            print(f"ERROR: Active investigations already running: {[r.id for r in active_runs]}")
            return 1

        # Verify evidence docs
        docs = conn.execute(
            select(ClaimEvidenceDocument).where(ClaimEvidenceDocument.claim_id == claim.id)
        ).fetchall()
        print(f"\nRetrieved Evidence Documents ({len(docs)}):")
        for d in docs:
            print(f"  - {d.filename} (status={d.storage_status}, size={d.file_size_bytes})")

        admin = conn.execute(
            select(Employee).where(Employee.email == "admin@claimsage.local")
        ).fetchone()
        if not admin:
            print("ERROR: Admin employee not found.")
            return 1
        token = create_access_token(admin.id)
        print("Admin token created.")

    # 2. Dispatch exactly ONE investigation
    print("\n=== STEP 2: DISPATCHING INVESTIGATION ===")
    task_desc = (
        "Investigate health insurance claim for emergency appendectomy hospitalization. "
        "Analyze medical records, itemized bills, and prescriptions against Demo Health Secure Plan 2026-V3. "
        "Verify diagnosis, treatment line, room rent charges against policy sub-limits, and exclusions."
    )
    req_body = json.dumps({
        "claim_id": claim_id,
        "task": task_desc,
    }).encode("utf-8")

    import os
    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    req = urllib.request.Request(
        f"{base_url}/api/v1/agent/investigations",
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode())
            print(f"HTTP Status: {resp.status}")
            print(f"Response: {resp_data}")
            new_run_id = resp_data.get("investigation_id")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}")
        return 1

    if not new_run_id:
        print("ERROR: No investigation_id returned!")
        return 1

    print(f"\n>>> Dispatched new investigation: {new_run_id}")

    # 3. Monitor execution until terminal status
    print("\n=== STEP 3: MONITORING EXECUTION (Worker Processing) ===")
    start_time = time.time()
    terminal_statuses = {"completed", "incomplete", "failed"}
    last_stage = None
    final_run = None

    while True:
        elapsed = time.time() - start_time
        with engine.connect() as conn:
            run = conn.execute(
                select(InvestigationRun).where(InvestigationRun.id == UUID(new_run_id))
            ).fetchone()

            if run:
                stage = run.current_stage
                status = run.status
                if stage != last_stage or status in terminal_statuses:
                    print(f"[{elapsed:6.1f}s] Status: {status:10s} | Stage: {str(stage):25s} | Worker: {run.worker_id}")
                    last_stage = stage

                if status in terminal_statuses:
                    print(f"[{elapsed:6.1f}s] Terminal status reached: {status.upper()}")
                    final_run = run
                    break

        if elapsed > 450:  # 7.5 minute timeout safety for full paced pipeline
            print("ERROR: Monitoring timed out after 450s")
            break
        time.sleep(3)

    # 4. Post-investigation in-depth verification
    print("\n=== STEP 4: VERIFYING RESULTS & PERSISTENCE ===")
    with engine.connect() as conn:
        run = conn.execute(
            select(InvestigationRun).where(InvestigationRun.id == UUID(new_run_id))
        ).fetchone()

        print(f"Final Run Status: {run.status}")
        print(f"Failure Type: {run.failure_type}")
        print(f"Human Review Status: {run.human_review_status}")

        report = conn.execute(
            select(InvestigationReport).where(InvestigationReport.investigation_id == UUID(new_run_id))
        ).fetchone()

        if report:
            print(f"\nInvestigation Report Present:")
            print(f"  Report ID: {report.id}")
            print(f"  Status: {report.status}")
            print(f"  Human Review Required: {report.human_review_required}")

            rdata = report.report_data if isinstance(report.report_data, dict) else {}
            exec_summary = rdata.get("executive_summary", "")
            print(f"\nExecutive Summary:\n{exec_summary}")
            print(f"\nEvidence Sufficiency: {rdata.get('evidence_sufficiency')}")
            print(f"Policy Alignment: {rdata.get('policy_alignment')}")
            print(f"Recommendations:\n{rdata.get('recommendations')}")

            # Inspect stage diagnostics
            diagnostics = rdata.get("stage_diagnostics", {})
            print(f"\nStage Diagnostics ({len(diagnostics)} stages recorded):")
            for stg, diag in diagnostics.items():
                print(f"  Stage: {stg:25s} | Status: {diag.get('status')} | InTokens: {diag.get('estimated_input_tokens')} | PromptTokens: {diag.get('actual_prompt_tokens')} | CompTokens: {diag.get('actual_completion_tokens')} | Duration: {diag.get('execution_duration')}s")

            # Check sources and findings
            sources = rdata.get("sources", [])
            print(f"\nSources Cited: {len(sources)}")
            for src in sources[:5]:
                print(f"  - Doc: {src.get('filename')} (Page {src.get('page_number')}) Chunk: {src.get('chunk_id')}")

        findings = conn.execute(
            select(InvestigationFinding).where(InvestigationFinding.investigation_id == UUID(new_run_id))
        ).fetchall()
        print(f"\nPersisted Findings ({len(findings)}):")
        for f in findings:
            spec = getattr(f, "specialist", "") or ""
            ftype = getattr(f, "finding_type", "") or ""
            conf = getattr(f, "confidence", "")
            sev = getattr(f, "severity", "")
            print(f"  - [{spec}] type={ftype} sev={sev} conf={conf}")

    print("\n=== PHASE 3 INVESTIGATION EXECUTION FINISHED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
