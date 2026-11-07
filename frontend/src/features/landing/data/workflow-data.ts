export interface WorkflowStep {
  stepNumber: number
  title: string
  shortLabel: string
  category: 'ingestion' | 'retrieval' | 'specialist' | 'synthesis' | 'governance'
  condition?: string
  description: string
  inputs: string[]
  outputs: string[]
  processingPill: string
  safetyCheck: string
}

export const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    stepNumber: 1,
    title: 'Claim Intake & Manifest Validation',
    shortLabel: 'Claim Intake',
    category: 'ingestion',
    description:
      'The intake agent audits submitted PDFs, photos, and medical bills for legibility, cryptographic file integrity (SHA-256), and completeness against mandatory checklist requirements.',
    inputs: ['Uploaded claim PDFs / images', 'Claimant declaration metadata', 'Checklist requirements schema'],
    outputs: ['Audit-ready document inventory', 'Data quality diagnostics', 'Missing essential documents list'],
    processingPill: 'intake_agent.py · SHA-256 Check',
    safetyCheck: 'Validates file tamper resistance and unreadable document exclusions before ingestion.',
  },
  {
    stepNumber: 2,
    title: 'Contextual Hybrid RAG Retrieval',
    shortLabel: 'Evidence Retrieval',
    category: 'retrieval',
    description:
      'Chunks text into 500-char segments with 100-char overlap. Computes 384-dimensional dense vectors with all-MiniLM-L6-v2 and runs concurrent lexical tsvector inverted queries, fusing them via Reciprocal Rank Fusion (RRF).',
    inputs: ['Parsed document chunks', 'Policy clause database', 'Agent search queries'],
    outputs: ['Canonical evidence chunks', 'RRF ranked candidate passages', 'Chunk authorization tokens'],
    processingPill: 'PostgreSQL pgvector + tsvector · RRF Fusion',
    safetyCheck: 'Cross-tenant authorization filter ensures only chunks associated with the active claim_id can be returned.',
  },
  {
    stepNumber: 3,
    title: 'Cross-Document Evidence Analysis',
    shortLabel: 'Evidence Analysis',
    category: 'specialist',
    description:
      'Constructs a chronological event timeline from discharge summaries, consultation notes, and police FIRs. Binds every clinical or vehicular event to an immutable evidence_id and exact verbatim quote.',
    inputs: ['Ranked claim evidence chunks', 'Event categorization schema'],
    outputs: ['Chronological event timeline', 'Cross-document assertion conflicts', 'Unverified timeline gaps'],
    processingPill: 'evidence_analyst.py · Timeline Synthesis',
    safetyCheck: 'Deterministic substring validator ensures no hallucinated events are placed in state.',
  },
  {
    stepNumber: 4,
    title: 'Policy Clause & Sub-Limit Evaluation',
    shortLabel: 'Policy Analysis',
    category: 'specialist',
    description:
      'Cross-references clinical diagnosis and treatment codes with specific policy clauses, checking room-rent sub-limits (e.g. 1% of Sum Insured), co-pay requirements, and pre-existing disease waiting periods.',
    inputs: ['Verified claim timeline & line items', 'Policy clause chunks', 'Active policy endorsements'],
    outputs: ['Coverage status indicators', 'Exclusion triggers & waiting period calculations', 'Proportionate deduction schedules'],
    processingPill: 'policy_analyst.py · Clause Grounding',
    safetyCheck: 'Exclusion checks require explicit continuous coverage validation from policy database.',
  },
  {
    stepNumber: 5,
    title: 'Repair Estimate Arithmetic Verification',
    shortLabel: 'Repair Estimate',
    category: 'specialist',
    condition: 'Motor Claims Only (Bypassed for Health)',
    description:
      'Executes deterministic arithmetic recalculation on vehicle repair estimates. Applies statutory depreciation schedules (plastic, glass, metal) and verifies garage labor hours against regional caps.',
    inputs: ['Itemized garage estimate', 'Vehicle age & parts specification', 'repair_estimate_rules.py'],
    outputs: ['Reconciled parts & labor subtotals', 'Depreciation breakdown', 'Compulsory deductible deduction'],
    processingPill: 'repair_estimate_rules.py · Arithmetic Engine',
    safetyCheck: 'Automated conditional branch: Supervisor skips this step for health claims with zero delay.',
  },
  {
    stepNumber: 6,
    title: 'Risk & Anomaly Discrepancy Detection',
    shortLabel: 'Risk & Anomaly',
    category: 'specialist',
    description:
      'Surfaces timeline contradictions, double-billing codes, and abnormal diagnostic itemization while maintaining a strict, non-negotiable boundary between observable facts and unproven hypotheses.',
    inputs: ['Aggregated specialist outputs', 'Itemized billing records', 'Clinical guidelines'],
    outputs: ['Observable anomalies with dual citations', 'Testable investigative hypotheses', 'Recommended follow-ups'],
    processingPill: 'risk_anomaly_agent.py · Fact-Hypothesis Isolation',
    safetyCheck: 'Strict architectural ban prevents the AI model from making subjective fraud accusations.',
  },
  {
    stepNumber: 7,
    title: 'Executive Dossier Synthesis & Fallback',
    shortLabel: 'Report Synthesis',
    category: 'synthesis',
    description:
      'Synthesizes all specialist findings into an executive report with RFC 6901 JSON pointer citations. If external LLM rate limits hit, Deterministic Fallback Mode aggregates upstream outputs with zero hallucination.',
    inputs: ['All completed specialist states', 'reconcile_specialist_missing_in_state()'],
    outputs: ['Executive investigation dossier', 'RFC 6901 deep-link pointers', 'Deterministic fallback guarantee'],
    processingPill: 'review_report_agent.py · Quote Verification',
    safetyCheck: 'Every single claim finding is validated against original source chunks before database persistence.',
  },
  {
    stepNumber: 8,
    title: 'Mandatory Human Review & Determination',
    shortLabel: 'Human Sign-off',
    category: 'governance',
    description:
      'Licensed claims adjusters review findings, inspect cited source documents side-by-side, modify or override any interpretation, and record final determination notes in an immutable audit ledger.',
    inputs: ['Synthesized investigation dossier', 'Adjuster judgment & policy authority'],
    outputs: ['Signed investigation report', 'Adjuster overrides & rationale', 'Append-only audit ledger entry'],
    processingPill: 'Human Investigator Queue · Final Sign-off',
    safetyCheck: 'Strictly assistive copilot: ClaimSage NEVER autonomously pays, denies, or settles claims.',
  },
]
