import { apiClient } from '@/lib/api-client'
import type { Claim } from '@/types/claims'
import type {
  ClaimEvidenceUploadResponse,
  InvestigationResponse,
} from '@/types/claim-workspace'
import type { AuditTimelineResponse, CustomerEmail } from '@/types/investigations'

export async function getClaim(claimId: string): Promise<Claim> {
  const { data } = await apiClient.get<Claim>(
    `/claims/${encodeURIComponent(claimId)}`,
  )
  return data
}

export interface CreateClaimPayload {
  claim_number: string
  claimant_name: string
  claim_type: string
  summary?: string | undefined
  loss_date?: string | undefined
  policy_identifier?: string | undefined
  insurer_name?: string | undefined
  product_name?: string | undefined
  team_id?: string | undefined
}

export async function createClaim(payload: CreateClaimPayload): Promise<Claim> {
  const { data } = await apiClient.post<Claim>('/claims', payload)
  return data
}

export async function updateClaimPolicyMetadata(
  claimId: string,
  payload: {
    policy_identifier: string
    insurer_name?: string
    product_name?: string
    loss_date: string
    verified_against_source: true
  },
): Promise<Claim> {
  const { data } = await apiClient.patch<Claim>(
    `/claims/${encodeURIComponent(claimId)}/policy-metadata`,
    payload,
  )
  return data
}

export async function uploadClaimEvidence(
  claimId: string,
  file: File,
  onProgress: (progress: number) => void,
): Promise<ClaimEvidenceUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await apiClient.post<ClaimEvidenceUploadResponse>(
    `/claims/${encodeURIComponent(claimId)}/evidence`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100))
        }
      },
    },
  )
  return data
}

export async function createInvestigation(
  claimId: string,
  task: string,
  repairEstimateDocumentId?: string,
): Promise<InvestigationResponse> {
  const payload: {
    claim_id: string
    task: string
    repair_estimate_document_id?: string
  } = { claim_id: claimId, task }
  if (repairEstimateDocumentId) {
    payload.repair_estimate_document_id = repairEstimateDocumentId
  }

  const { data } = await apiClient.post<InvestigationResponse>(
    '/agent/investigations',
    payload,
  )
  return data
}

export async function getClaimEmails(claimId: string): Promise<CustomerEmail[]> {
  const { data } = await apiClient.get<CustomerEmail[]>(
    `/claims/${encodeURIComponent(claimId)}/emails`,
  )
  return data
}

export async function createCustomerEmailDraft(
  claimId: string,
  payload: {
    event_type: string
    recipient_email: string
    recipient_name: string
    subject?: string
    body_text?: string
    body_html?: string
    requested_documents?: string[]
    follow_up_days?: number
  },
): Promise<CustomerEmail> {
  const { data } = await apiClient.post<CustomerEmail>(
    `/claims/${encodeURIComponent(claimId)}/emails`,
    payload,
  )
  return data
}

export async function approveCustomerEmail(
  claimId: string,
  emailId: string,
): Promise<CustomerEmail> {
  const { data } = await apiClient.post<CustomerEmail>(
    `/claims/${encodeURIComponent(claimId)}/emails/${encodeURIComponent(emailId)}/approve`,
  )
  return data
}

export async function sendCustomerEmail(
  claimId: string,
  emailId: string,
): Promise<CustomerEmail> {
  const { data } = await apiClient.post<CustomerEmail>(
    `/claims/${encodeURIComponent(claimId)}/emails/${encodeURIComponent(emailId)}/send`,
  )
  return data
}

export async function getClaimAuditTimeline(
  claimId: string,
  params?: {
    event_category?: string
    actor_type?: string
    outcome?: string
    limit?: number
    offset?: number
  },
): Promise<AuditTimelineResponse> {
  const { data } = await apiClient.get<AuditTimelineResponse>(
    `/claims/${encodeURIComponent(claimId)}/audit`,
    { params },
  )
  return data
}
