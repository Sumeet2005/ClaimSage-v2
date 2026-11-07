export interface AgentDefinition {
  id: string
  name: string
  sourceFile: string
  role: string
  executionOrder: number
  category: 'supervisor' | 'specialist' | 'synthesis'
  colorTone: 'forest' | 'emerald' | 'champagne' | 'graphite'
  contract: string
  inputDependencies: string[]
  keyResponsibilities: string[]
  deterministicRules: string[]
  samplePayload: {
    status: string
    confidence: number
    findingsSummary: string
    citationsCount: number
    rawJson: Record<string, unknown>
  }
}

export const CLAIM_AGENTS: AgentDefinition[] = [
  {
    id: 'supervisor',
    name: 'Supervisor Agent',
    sourceFile: 'supervisor.py',
    role: 'Dynamic Investigation Graph Orchestrator',
    executionOrder: 1,
    category: 'supervisor',
    colorTone: 'forest',
    contract: 'SupervisorPlan(selected_analysts, routing_rationale, human_review_required)',
    inputDependencies: [
      'Claim header facts (claim_id, loss_type, claim_amount)',
      'Uploaded document metadata & MIME types',
      'Policy classification (health vs motor)',
    ],
    keyResponsibilities: [
      'Inspects claim facts and document manifests before any LLM invocations',
      'Dynamically routes Motor claims through repair estimate analysis and bypasses for Health claims',
      'Calculates pre-invocation token allocations via TokenBudgetManager',
      'Enforces human-in-the-loop review flag for high-severity or ambiguous claims',
    ],
    deterministicRules: [
      'Motor claims with estimate documents MUST execute RepairEstimateAnalyst',
      'Health claims MUST bypass RepairEstimateAnalyst without penalty',
      'Zero downstream specialist activation if required claim intake fails validation',
    ],
    samplePayload: {
      status: 'planned',
      confidence: 1.0,
      findingsSummary: 'Plan generated: 5 specialists assigned. Repair analysis bypassed for health claim.',
      citationsCount: 0,
      rawJson: {
        selected_analysts: [
          'intake_agent',
          'evidence_analyst',
          'policy_analyst',
          'risk_anomaly_agent',
          'review_report_agent',
        ],
        routing_rationale:
          'Claim type health verified. Discharged from Apollo Hospitals. Sum insured 500,000 INR. Repair estimate skipped.',
        human_review_required: true,
        estimated_token_budget: 4200,
      },
    },
  },
  {
    id: 'intake',
    name: 'Claim Intake Agent',
    sourceFile: 'intake_agent.py',
    role: 'Document Inventory & Ingestion Auditor',
    executionOrder: 2,
    category: 'specialist',
    colorTone: 'emerald',
    contract: 'IntakeDocumentOutput(document_inventory, missing_information, data_quality_issues)',
    inputDependencies: [
      'Raw document text chunks from MinIO object store',
      'Claim file metadata & file format declarations',
      'Mandatory document requirements checklist',
    ],
    keyResponsibilities: [
      'Builds complete verifiable inventory of all submitted PDFs and summaries',
      'Verifies document legibility, OCR quality, and digital signature validity',
      'Flags missing essential documents (Discharge Summary, Indoor Case Papers, Final Bill)',
      'Extracts initial verified admission, discharge, and itemized billing dates',
    ],
    deterministicRules: [
      'Discharge summary missing from hospitalization claim immediately triggers missing_information flag',
      'Document SHA-256 hash verified against MinIO storage manifest before text chunk parsing',
    ],
    samplePayload: {
      status: 'completed',
      confidence: 0.98,
      findingsSummary: '3 documents indexed: Discharge Summary, Itemized Hospital Bill, Pharmacy Receipts.',
      citationsCount: 3,
      rawJson: {
        document_inventory: [
          { doc_id: 'doc-001', type: 'discharge_summary', pages: 3, ocr_quality: 'high' },
          { doc_id: 'doc-002', type: 'final_hospital_bill', pages: 2, ocr_quality: 'high' },
          { doc_id: 'doc-003', type: 'pharmacy_invoices', pages: 1, ocr_quality: 'medium' },
        ],
        missing_information: [
          { field: 'indoor_case_papers', criticality: 'moderate', reason: 'ICU stay over 48 hours requires detailed chart' },
        ],
        data_quality_issues: [],
      },
    },
  },
  {
    id: 'evidence',
    name: 'Evidence Analyst',
    sourceFile: 'evidence_analyst.py',
    role: 'Chronological Timeline & Conflict Extractor',
    executionOrder: 3,
    category: 'specialist',
    colorTone: 'emerald',
    contract: 'EvidenceAnalystOutput(observed_facts, timeline, conflicts, evidence_gaps)',
    inputDependencies: [
      'Retrieved claim evidence chunks via pgvector Cosine + Lexical search',
      'Standardized event categorization schema',
    ],
    keyResponsibilities: [
      'Constructs millisecond-accurate chronological event sequence of medical or collision events',
      'Binds every single observed fact to an immutable chunk_id and exact verbatim quote',
      'Identifies conflicting statements between claimant loss report and medical record entries',
      'Logs evidence gaps where dates or timestamps show unverified lapses',
    ],
    deterministicRules: [
      'Zero facts permitted in state without exact substring match against chunk provenance',
      'Contradictory dates across doctor notes and discharge summary must be surfaced as explicit conflict',
    ],
    samplePayload: {
      status: 'completed',
      confidence: 0.96,
      findingsSummary: 'Timeline composed of 7 clinical events with verified verbatim evidence citations.',
      citationsCount: 7,
      rawJson: {
        observed_facts: [
          {
            fact: 'Patient admitted on 2026-10-12 at 08:30 for acute laparoscopic cholecystectomy',
            evidence_id: 'chk-8839-a1',
            verbatim_quote: 'admitted on 12/10/2026 08:30 hrs through Emergency OPD',
          },
          {
            fact: 'Transferred to ICU Room 402 for postoperative monitoring for 36 hours',
            evidence_id: 'chk-8839-a2',
            verbatim_quote: 'shifted to ICU 402 at 14:15 hrs post operative vitals stable',
          },
        ],
        conflicts: [],
        evidence_gaps: ['Pre-operative anesthesia clearance certificate missing'],
      },
    },
  },
  {
    id: 'policy',
    name: 'Policy Analyst',
    sourceFile: 'policy_analyst.py',
    role: 'Clause Grounding & Sub-limit Verifier',
    executionOrder: 4,
    category: 'specialist',
    colorTone: 'champagne',
    contract: 'PolicyAnalystOutput(coverage_indicators, exclusions_and_conditions, missing_information, evidence_gaps)',
    inputDependencies: [
      'Claim facts & verified line-item totals',
      'Canonical policy clause chunks from pgvector policy index',
      'Active policy schedule & endorsement riders',
    ],
    keyResponsibilities: [
      'Evaluates policy wordings against verified medical diagnoses and procedures',
      'Computes room-rent sub-limits (e.g., 1% of Sum Insured per day) and ICU caps (2%)',
      'Screens for 30-day initial waiting periods, 2-year specific ailment exclusions, and PED disclosures',
      'Calculates proportionate deduction on associated hospital medical charges',
    ],
    deterministicRules: [
      'Clause 4.1 Room Rent: Daily room charges exceeding INR 5,000 trigger proportionate deduction formula',
      'Pre-existing disease exclusion (Clause 4.8) requires 36 months continuous policy coverage check',
    ],
    samplePayload: {
      status: 'completed',
      confidence: 0.95,
      findingsSummary: 'Coverage verified under Plan Gold. Room rent capping limit applied to 2 ICU days.',
      citationsCount: 5,
      rawJson: {
        coverage_indicators: [
          { clause: 'Clause 2.1', description: 'In-patient Hospitalization Treatment', status: 'covered' },
          { clause: 'Clause 4.1', description: 'Room Rent Capping @ 1% of SI (INR 5,000/day)', status: 'limit_exceeded_partial_admissible' },
        ],
        exclusions_and_conditions: [
          { clause: 'Clause 4.8', term: 'Pre-existing Condition (Hypertension)', finding: 'Policy active 48 months; waiting period satisfied' },
        ],
      },
    },
  },
  {
    id: 'repair',
    name: 'Repair Estimate Analyst',
    sourceFile: 'repair_estimate_analyst.py',
    role: 'Deterministic Arithmetic & Parts Depreciation Engine',
    executionOrder: 5,
    category: 'specialist',
    colorTone: 'graphite',
    contract: 'RepairEstimateAnalystOutput(line_items, labor_subtotal, parts_subtotal, deductible_applied)',
    inputDependencies: [
      'Vehicle damage estimate line items (labor hours, paint rates, spare parts pricing)',
      'Motor insurance policy deductible & zero-depreciation endorsement metadata',
      'Deterministic arithmetic evaluator (repair_estimate_rules.py)',
    ],
    keyResponsibilities: [
      'Performs independent line-item arithmetic recalculation for labor and parts subtotals',
      'Applies statutory depreciation tiers (Plastic 50%, Glass 0%, Metallic 0-50% by vehicle age)',
      'Cross-checks labor hours against vehicle manufacturer standard flat-rate times',
      'Verifies compulsory policy deductible subtraction',
    ],
    deterministicRules: [
      'Arithmetic totals must strictly match sum of unit_price * quantity',
      'Standard labor rate cap enforced at INR 950/hr for non-authorized garage estimates',
      'Conditioned execution: Skipped automatically if claim_type == "health"',
    ],
    samplePayload: {
      status: 'conditional_active',
      confidence: 0.99,
      findingsSummary: 'Motor claim line items verified. Metallic panel depreciation applied at 20% tier.',
      citationsCount: 4,
      rawJson: {
        labor_subtotal: 14200.0,
        parts_subtotal: 38500.0,
        depreciation_subtotal: 7700.0,
        compulsory_deductible: 1000.0,
        net_assessed_estimate: 44000.0,
        arithmetic_reconciled: true,
      },
    },
  },
  {
    id: 'risk',
    name: 'Risk & Anomaly Agent',
    sourceFile: 'risk_anomaly_agent.py',
    role: 'Discrepancy & Plausibility Checker',
    executionOrder: 6,
    category: 'specialist',
    colorTone: 'champagne',
    contract: 'RiskAnomalyOutput(observed_facts, anomalies, hypotheses, missing_information)',
    inputDependencies: [
      'Combined findings from Intake, Evidence, and Policy specialists',
      'Cross-referenced billing totals and clinical diagnosis notes',
    ],
    keyResponsibilities: [
      'Detects timeline inconsistencies between accident report times and ER admissions',
      'Identifies unbundled billing codes or duplicate diagnostic tests across invoices',
      'Maintains a rigid boundary: observed facts vs testable investigative hypotheses',
      'Strictly prohibited from asserting definitive fraud or bad-faith allegations',
    ],
    deterministicRules: [
      'PROHIBITION: Cannot output legal conclusions or fraud accusations',
      'Every anomaly must cite both contradictory source passages with evidence IDs',
      'Hypotheses must explicitly specify investigator follow-up action required',
    ],
    samplePayload: {
      status: 'completed',
      confidence: 0.91,
      findingsSummary: '1 billing anomaly detected: Diagnostic ultrasound billed twice under different codes.',
      citationsCount: 2,
      rawJson: {
        anomalies: [
          {
            item: 'USG Abdomen Whole',
            issue: 'Billed under CODE-USG-01 on 10/12 and CODE-IMG-09 on 10/13 without corresponding radiology report',
            severity: 'moderate',
            evidence_ids: ['chk-bill-02', 'chk-bill-04'],
          },
        ],
        hypotheses: [
          {
            statement: 'Potential duplicate data entry during discharge billing settlement',
            suggested_action: 'Request hospital radiology logs for confirmation of second scan',
          },
        ],
      },
    },
  },
  {
    id: 'review_report',
    name: 'Review & Report Agent',
    sourceFile: 'review_report_agent.py',
    role: 'Executive Dossier Synthesis & Fallback Manager',
    executionOrder: 7,
    category: 'synthesis',
    colorTone: 'forest',
    contract: 'ReviewReportOutput(observed_facts, analyst_interpretations, hypotheses, conflicting_findings, missing_information, report_status)',
    inputDependencies: [
      'Structured outputs from all completed upstream specialist agents',
      'Evidence reconciliation state (reconcile_specialist_missing_in_state)',
      'RFC 6901 JSON pointer mapper for frontend interactive highlights',
    ],
    keyResponsibilities: [
      'Compiles cohesive executive report organized into facts, interpretations, and hypotheses',
      'Validates all verbatim quotes against canonical chunk texts before final compilation',
      'Injects RFC 6901 output_path pointers for instantaneous claim-detail navigation',
      'Executes Deterministic Fallback Mode if third-party LLM rate limits (HTTP 429) occur',
    ],
    deterministicRules: [
      'Zero hallucinated findings: Unverified facts rejected during report assembly',
      'Deterministic fallback triggers when cloud LLM is unreachable, preventing workflow abort',
      'Final status marked pending_human_review: Zero autonomous approval or denial',
    ],
    samplePayload: {
      status: 'completed',
      confidence: 0.97,
      findingsSummary: 'Executive report synthesized. 100% evidence provenance validated.',
      citationsCount: 16,
      rawJson: {
        report_status: 'ready_for_review',
        generation_mode: 'ai_synthesis',
        human_review_required: true,
        summary_verdict: 'Admissible subject to room rent capping deduction and ultrasound reconciliation',
        total_claimed: 145000.0,
        assessed_indicative: 128400.0,
        pending_investigator_action: 'Verify duplicate USG invoice before final sign-off',
      },
    },
  },
]
