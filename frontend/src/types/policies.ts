export type InsuranceType = 'health' | 'auto' | 'property'
export type PolicyStatus = 'uploaded' | 'processing' | 'processed' | 'failed'
export type ExclusionType =
  | 'permanent'
  | 'waiting_period'
  | 'condition_based'
  | 'specified_illness'
  | 'other'
export type ClauseVerificationStatus = 'pending_review' | 'verified' | 'needs_review'

export interface PolicyCoverage {
  id: string
  document_id: string
  coverage_name: string
  coverage_category: string
  benefit_limit: string | number | null
  deductible: string | number | null
  co_pay_percentage: string | number | null
  waiting_period_days: number | null
  description: string | null
  is_optional: boolean
  created_at: string
}

export interface PolicyCoverageCreateRequest {
  coverage_name: string
  coverage_category?: string
  benefit_limit?: number | null
  deductible?: number | null
  co_pay_percentage?: number | null
  waiting_period_days?: number | null
  description?: string | null
  is_optional?: boolean
}

export interface PolicyExclusion {
  id: string
  document_id: string
  exclusion_code: string | null
  title: string
  description: string
  waiting_period_months: number | null
  exclusion_type: ExclusionType
  created_at: string
}

export interface PolicyExclusionCreateRequest {
  exclusion_code?: string | null
  title: string
  description: string
  waiting_period_months?: number | null
  exclusion_type?: ExclusionType
}

export interface PolicySummary {
  id: string
  policy_identifier: string
  insurer_name: string | null
  product_name: string | null
  insurance_type: string | null
  policy_version: string | null
  effective_from: string | null
  effective_to: string | null
  status: PolicyStatus
  has_document_attached: boolean
  chunk_count: number
  clause_count: number
  coverage_count: number
  exclusion_count: number
  created_at: string | null
  updated_at: string | null
}

export interface PolicyDetail extends PolicySummary {
  filename: string | null
  file_size_bytes: number
  source_url: string | null
  supported_claim_types: string[]
  coverages: PolicyCoverage[]
  exclusions: PolicyExclusion[]
  linked_claims_count: number
}

export interface PolicyCreateRequest {
  policy_identifier: string
  insurer_name: string
  product_name: string
  insurance_type?: InsuranceType
  policy_version?: string
  effective_from: string
  effective_to?: string | null
  source_url?: string | null
  supported_claim_types?: string[]
  coverages?: PolicyCoverageCreateRequest[]
  exclusions?: PolicyExclusionCreateRequest[]
}

export interface PolicyUpdateRequest {
  insurer_name?: string | null
  product_name?: string | null
  policy_version?: string | null
  effective_from?: string | null
  effective_to?: string | null
  source_url?: string | null
  status?: PolicyStatus | null
}

export interface PolicyClause {
  id: string
  document_id: string
  source_chunk_id: string
  clause_identifier: string
  clause_category: string
  title: string | null
  clause_text: string
  source_page_number: number
  verification_status: ClauseVerificationStatus
  verified_by_employee_id: string | null
  verified_at: string | null
}

export interface PolicyClaimLinkRequest {
  claim_id: string
}

export interface PolicyClaimLinkResponse {
  policy_id: string
  claim_id: string
  claim_number: string
  policy_identifier: string
  insurer_name: string | null
  product_name: string | null
  linked_at: string
}

export interface PolicyLinkedClaim {
  id: string
  claim_number: string
  claimant_name: string
  claim_type: string
  status: string
  loss_date: string | null
  created_at: string | null
}
