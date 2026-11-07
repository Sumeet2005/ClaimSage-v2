export type ClaimDomain = 'auto' | 'health' | 'other'
export type InvestigationStatus =
  | 'running'
  | 'completed'
  | 'incomplete'
  | 'failed'
export type HumanReviewStatus =
  | 'pending'
  | 'approved'
  | 'needs_additional_documents'
  | 'returned_for_investigation'
  | 'escalated'
  | 'reviewed'
  | 'needs_follow_up'
export type ReviewDecision = Exclude<HumanReviewStatus, 'pending'>
export type ReportStatus =
  | 'completed'
  | 'incomplete'
  | 'unavailable'
  | 'skipped'
export type EvidenceSufficiency =
  | 'sufficient_for_analysis'
  | 'insufficient_evidence'
  | 'undetermined'

export interface FindingEdit {
  id: string
  finding_id: string
  investigation_id: string
  editor_employee_id: string
  editor_name: string
  original_data: Record<string, unknown>
  edited_data: Record<string, unknown>
  reason: string
  created_at: string
}

export interface FindingEditRequest {
  edited_data: Record<string, unknown>
  reason: string
}

export type CustomerEmailStatus =
  | 'drafted'
  | 'approved'
  | 'queued'
  | 'sent'
  | 'bounced'
  | 'replied'
  | 'failed'

export type CustomerEmailEventType =
  | 'claim_received'
  | 'investigation_completed'
  | 'human_review_required'
  | 'additional_evidence_required'
  | 'review_completed'

export interface CustomerEmail {
  id: string
  claim_id: string
  investigation_id: string | null
  event_type: CustomerEmailEventType
  recipient_email: string
  recipient_name: string
  sender_email: string
  subject: string
  body_text: string
  body_html: string
  template_key: string
  status: CustomerEmailStatus
  approved_by_employee_id: string | null
  approved_by_name: string | null
  approved_at: string | null
  secure_upload_url: string | null
  follow_up_deadline: string | null
  reminder_sent_at: string | null
  attempt_count: number
  max_attempts: number
  last_error_type: string | null
  sent_at: string | null
  created_at: string
  updated_at: string
}

export interface InvestigationSummary {
  id: string
  claim_id: string
  claim_domain: ClaimDomain
  status: InvestigationStatus
  current_stage: string | null
  human_review_status: HumanReviewStatus
  report_status: ReportStatus | null
  evidence_sufficiency: EvidenceSufficiency | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface FindingReference {
  source_id: string
  resolved_from_retrieval?: boolean
  provenance?: Record<string, unknown>
  source_kind?: string
}

export interface InvestigationFinding {
  id: string
  specialist: string
  finding_type: string
  finding_data: Record<string, unknown>
  severity: string | null
  confidence: string | null
  evidence_references: FindingReference[]
  policy_references: FindingReference[]
  created_at: string
}

export interface InvestigationDetail extends InvestigationSummary {
  task: string
  failure_type: string | null
  state_snapshot: Record<string, unknown>
  findings: InvestigationFinding[]
}

export interface InvestigationReport {
  id: string
  investigation_id: string
  status: ReportStatus
  report_data: Record<string, unknown> | null
  limitations: string[]
  human_review_required: true
  created_at: string
  updated_at: string
}

export interface InvestigationReview {
  id: string
  investigation_id: string
  reviewer_employee_id: string
  reviewer_name: string
  decision: ReviewDecision
  notes: string | null
  created_at: string
}

export interface InvestigationReviewRequest {
  decision: ReviewDecision
  notes?: string | null
  requested_documents?: string[] | null
  escalate_reason?: string | null
}

export interface AuditEventItem {
  id: string
  actor_type: string
  actor_id: string | null
  actor_name: string
  actor_employee_id: string | null
  claim_id: string | null
  investigation_id: string | null
  event_category: string
  action: string
  outcome: string
  resource_type: string
  resource_id: string | null
  correlation_id: string | null
  details: string | null
  event_metadata: Record<string, unknown>
  created_at: string
}

export interface AuditTimelineResponse {
  items: AuditEventItem[]
  total_count: number
  limit: number
  offset: number
}

export interface InvestigationNotification {
  id: string
  event_type: string
  status: string
  attempt_count?: number
  last_error_type?: string | null
  created_at: string
  updated_at?: string
  delivered_at?: string | null
  recipient_email?: string | null
  recipient_name?: string | null
  subject?: string | null
  message?: string | null
  secure_upload_url?: string | null
  is_draft?: boolean
}
