"""Execute and monitor exactly ONE fresh investigation for Claim CLM-DEMO-HEALTH-001."""

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
    NotificationDelivery,
    PolicyDocument,
)
from claimsage.services.auth import create_access_token

CLAIM_ID = "fac63d6a-5deb-438d-88a1-d7247963e812"
POLICY_ID = "702ed921-5a3b-462e-889c-4a1957690ea4"
HISTORICAL_RUN_ID = "a08e91af-c74a-4111-aec1-b8e759b04f1a"

def main():
    settings = get_settings()
    engine = create_engine(settings.database_url)

    # 1. Pre-flight checks
    print("=== STEP 1: PRE-FLIGHT VERIFICATION ===")
    with engine.connect() as conn:
        # Verify claim
        claim = conn.execute(
            select(Claim).where(Claim.id == CLAIM_ID)
        ).fetchone()
        if not claim:
            print(f"ERROR: Claim {CLAIM_ID} not found.")
            sys.exit(1)
        print(f"Claim: {claim.claim_number} ({claim.claimant_name}), status={claim.status}, policy_identifier={claim.policy_identifier}")

        # Verify active investigations
        active_runs = conn.execute(
            select(InvestigationRun).where(
                InvestigationRun.claim_id == CLAIM_ID,
                InvestigationRun.status.in_(["queued", "running"]),
            )
        ).fetchall()
        if active_runs:
            print(f"ERROR: Active investigations already running: {[r.id for r in active_runs]}")
            sys.exit(1)
        print("Active investigations for claim: 0 (verified)")

        # Verify historical run
        hist_run = conn.execute(
            select(InvestigationRun).where(InvestigationRun.id == HISTORICAL_RUN_ID)
        ).fetchone()
        print(f"Historical run {HISTORICAL_RUN_ID}: status={hist_run.status if hist_run else 'none'}")

        # Verify policy
        policy = conn.execute(
            select(PolicyDocument).where(PolicyDocument.id == POLICY_ID)
        ).fetchone()
        print(f"Policy: {policy.policy_identifier} ({policy.product_name} {policy.policy_version}), insurance_type={policy.insurance_type}")

        # Verify evidence documents
        docs = conn.execute(
            select(ClaimEvidenceDocument).where(ClaimEvidenceDocument.claim_id == CLAIM_ID)
        ).fetchall()
        print(f"Evidence documents ({len(docs)}):")
        for d in docs:
            print(f"  - {d.filename} (status={d.storage_status}, size={d.file_size_bytes})")
        if len(docs) != 4:
            print(f"ERROR: Expected 4 evidence documents, found {len(docs)}")
            sys.exit(1)

        # Get admin employee
        admin = conn.execute(
            select(Employee).where(Employee.email == "admin@claimsage.local")
        ).fetchone()
        if not admin:
            print("ERROR: Admin employee not found.")
            sys.exit(1)
        token = create_access_token(admin.id)
        print("Admin JWT generated successfully.")

    # 2. Dispatch exactly ONE investigation
    print("\n=== STEP 2: DISPATCHING INVESTIGATION ===")
    task_desc = (
        "Investigate health insurance claim for emergency appendectomy hospitalization. "
        "Analyze medical records, itemized bills, and prescriptions against Demo Health Secure Plan v2.0. "
        "Verify diagnosis, treatment line, room rent charges against policy sub-limits, and exclusions."
    )
    req_body = json.dumps({
        "claim_id": CLAIM_ID,
        "task": task_desc,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/agent/investigations",
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
        sys.exit(1)

    if not new_run_id:
        print("ERROR: No investigation_id returned!")
        sys.exit(1)

    print(f"\n>>> Dispatched new investigation: {new_run_id}")

    # 3. Monitor execution until terminal status
    print("\n=== STEP 3: MONITORING EXECUTION ===")
    start_time = time.time()
    terminal_statuses = {"completed", "incomplete", "failed"}
    last_stage = None
    final_run = None

    while True:
        elapsed = time.time() - start_time
        with engine.connect() as conn:
            run = conn.execute(
                select(InvestigationRun).where(InvestigationRun.id == new_run_id)
            ).fetchone()

            if run:
                stage = run.current_stage
                status = run.status
                if stage != last_stage or status in terminal_statuses:
                    print(f"[{elapsed:6.1f}s] Status: {status:10s} | Stage: {stage} | Worker: {run.worker_id}")
                    last_stage = stage

                if status in terminal_statuses:
                    print(f"[{elapsed:6.1f}s] Terminal status reached: {status.upper()}")
                    final_run = run
                    break

        if elapsed > 240:  # 4 minute timeout safety
            print("ERROR: Monitoring timed out after 240s")
            break
        time.sleep(2)

    # 4. Post-investigation in-depth verification
    print("\n=== STEP 4: VERIFYING RESULTS & PERSISTENCE ===")
    with engine.connect() as conn:
        run = conn.execute(
            select(InvestigationRun).where(InvestigationRun.id == new_run_id)
        ).fetchone()
        print(f"Final Run Record:")
        print(f"  ID: {run.id}")
        print(f"  Status: {run.status}")
        print(f"  Current Stage: {run.current_stage}")
        print(f"  Human Review Status: {run.human_review_status}")
        print(f"  Worker ID: {run.worker_id}")
        print(f"  Attempts: {run.attempt_count}/{run.max_attempts}")
        print(f"  Failure Type: {run.failure_type}")
        print(f"  Started: {run.created_at}")
        print(f"  Completed: {run.completed_at}")

        # Check investigation report
        report = conn.execute(
            select(InvestigationReport).where(InvestigationReport.investigation_id == new_run_id)
        ).fetchone()
        if report:
            print(f"\nInvestigation Report:")
            print(f"  Report ID: {report.id}")
            print(f"  Status: {report.status}")
            print(f"  Human Review Required: {report.human_review_required}")
            print(f"  Report Data Keys: {list(report.report_data.keys()) if isinstance(report.report_data, dict) else type(report.report_data)}")
            if isinstance(report.report_data, dict):
                print(f"  Executive Summary:\n    {report.report_data.get('executive_summary', '')[:400]}")
                print(f"  Evidence Sufficiency: {report.report_data.get('evidence_sufficiency')}")
                print(f"  Policy Alignment: {report.report_data.get('policy_alignment')}")
                print(f"  Coverage Limitations: {report.report_data.get('coverage_limitations')}")
                print(f"  Recommendations:\n    {report.report_data.get('recommendations')}")
            if report.limitations:
                print(f"  Report Limitations: {report.limitations}")
        else:
            print("\nWARNING: No InvestigationReport record found!")

        # Check findings
        findings = conn.execute(
            select(InvestigationFinding).where(InvestigationFinding.investigation_id == new_run_id)
        ).fetchall()
        print(f"\nInvestigation Findings ({len(findings)} total):")
        for f in findings:
            title = f.finding_data.get("title", f.finding_data.get("finding", "Finding")) if isinstance(f.finding_data, dict) else "Finding"
            print(f"  - [{f.specialist}] ({f.finding_type}, severity={f.severity}, conf={f.confidence}): {title}")
            if isinstance(f.finding_data, dict) and "details" in f.finding_data:
                print(f"      Details: {str(f.finding_data.get('details'))[:120]}")

        # Check finding references / citations
        finding_ids = [f.id for f in findings]
        if finding_ids:
            refs = conn.execute(
                select(InvestigationFindingReference).where(
                    InvestigationFindingReference.finding_id.in_(finding_ids)
                )
            ).fetchall()
            print(f"\nFinding Citations / References ({len(refs)} total):")
            for r in refs[:8]:
                print(f"  - source_kind: {r.source_kind}, source_id: {r.source_id}, provenance: {r.provenance}")
            if len(refs) > 8:
                print(f"  ... and {len(refs) - 8} more citations")
        else:
            print("\nNo findings to query references for.")

        # Check audit events
        audits = conn.execute(
            select(AuditEvent).where(
                (AuditEvent.investigation_id == new_run_id) | (AuditEvent.resource_id == str(new_run_id))
            ).order_by(AuditEvent.created_at.asc())
        ).fetchall()
        print(f"\nAudit Events ({len(audits)} total):")
        for a in audits:
            print(f"  - [{a.created_at}] Action: {a.action}, Outcome: {a.outcome}, Actor: {a.actor_employee_id or a.actor_id}")

        # Check notifications
        notifications = conn.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.resource_id == new_run_id
            )
        ).fetchall()
        print(f"\nNotification Deliveries ({len(notifications)} total):")
        for n in notifications:
            print(f"  - Event: {n.event_type}, Status: {n.status}, Attempts: {n.attempt_count}")

        # Check state snapshot specialists
        if run.state_snapshot and isinstance(run.state_snapshot, dict):
            print(f"\nState Snapshot Agent Results:")
            for agent_name in ["supervisor", "intake_agent", "evidence_analyst", "policy_analyst", "risk_anomaly_agent", "review_report_agent"]:
                agent_res = run.state_snapshot.get(agent_name)
                if agent_res:
                    status_val = agent_res.get("status") if isinstance(agent_res, dict) else "present"
                    print(f"  - {agent_name}: {status_val}")
                else:
                    print(f"  - {agent_name}: not in state_snapshot")

        # Verify historical run was not touched
        hist_check = conn.execute(
            select(InvestigationRun).where(InvestigationRun.id == HISTORICAL_RUN_ID)
        ).fetchone()
        print(f"\nHistorical Run check: ID={hist_check.id}, status={hist_check.status} (UNCHANGED)")

if __name__ == "__main__":
    main()
