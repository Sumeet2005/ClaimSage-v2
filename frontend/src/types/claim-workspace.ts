export interface ClaimEvidenceUploadResponse {
  document_id: string
  claim_id: string
  filename: string
  status: string
  chunk_count: number
}

export interface InvestigationResponse {
  investigation_id?: string | null
  execution_status: 'queued' | 'running' | 'completed' | 'incomplete' | 'failed'
  status?: string | null
  claim_facts?: Record<string, unknown> | null
  result?: Record<string, unknown> | null
  error?: string | null
}

export interface ReviewReportSource {
  evidence_id: string
  document_id: string
  filename: string
  page_number: number
}

export type DocumentEvidenceStatus =
  | 'uploaded_not_retrieved'
  | 'retrieved'
  | 'partially_available'
  | 'retrieved_unverified'
  | 'verified'
  | 'not_provided'
  | 'not_applicable'
  | 'conflicting'

export type MissingInformationCategory =
  | DocumentEvidenceStatus
  | 'not_retrieved'

export interface MissingInformationReconciliationItem {
  field_or_topic: string
  original_statement: string
  originating_specialist?: string | null
  reconciled_category: MissingInformationCategory
  available_in_sources: string[]
  supporting_evidence_ids: string[]
  extracted_value?: string | null
  retained_in_missing_information: boolean
  reconciliation_note: string
  human_review_required: boolean
}

export interface ReportSourceInventoryItem {
  document_id: string
  filename: string
  document_type: string
  document_status?: DocumentEvidenceStatus
  processing_status: string
  retrieval_status: string
  used_by_specialists: string[]
  evidence_ids: string[]
  page_numbers: number[]
  citation_count: number
  verification_status?: string | null
}

export interface ReviewReportItem {
  statement: string
  explanation: string
  supporting_evidence_ids: string[]
  supporting_quotes: Array<{ evidence_id: string; quote: string }>
  sources: ReviewReportSource[]
  analyst_output_references: Array<{
    specialist: string
    output_path: string
    finding_text: string
  }>
  source_basis: string
  limitation: string | null
  originating_specialist?: string | null
  attribution_status?: 'verified' | 'unverified' | 'system_derived'
  missing_category?: MissingInformationCategory | null
}

export interface ReviewReportSpecialistCoverage {
  specialist: string
  status: string
  analysis_included: boolean
  limitations: string[]
}

export interface ReviewReport {
  overall_status: string
  report_generation_mode?: 'ai_generated' | 'deterministic_fallback'
  observed_facts: ReviewReportItem[]
  analyst_interpretations: ReviewReportItem[]
  hypotheses: ReviewReportItem[]
  conflicting_findings: ReviewReportItem[]
  missing_information: ReviewReportItem[]
  specialist_coverage: ReviewReportSpecialistCoverage[]
  evidence_retrieval_status: string
  evidence_retrieval_limitations: string[]
  evidence_scope_note: string
  human_review_required: true
  report_completeness?: 'complete' | 'partial' | 'insufficient_evidence'
  report_validation_status?:
    | 'validated'
    | 'validated_with_warnings'
    | 'flagged_for_human_review'
    | 'validation_failed'
    | 'not_validated'
  policy_verification_status?:
    | 'verified'
    | 'pending_review'
    | 'unverified'
    | 'not_retrieved'
    | 'not_applicable'
  source_inventory?: ReportSourceInventoryItem[]
  missing_information_reconciliation?: MissingInformationReconciliationItem[]
  validation_warnings?: string[]
  validation_failures?: string[]
}
