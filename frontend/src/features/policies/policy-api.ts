import { apiClient } from '@/lib/api-client'
import type {
  PolicyClaimLinkResponse,
  PolicyClause,
  PolicyCoverage,
  PolicyCoverageCreateRequest,
  PolicyCreateRequest,
  PolicyDetail,
  PolicyExclusion,
  PolicyExclusionCreateRequest,
  PolicyLinkedClaim,
  PolicySummary,
  PolicyUpdateRequest,
} from '@/types/policies'

export async function getPolicies(params?: {
  query?: string | undefined
  insurer_name?: string | undefined
  insurance_type?: string | undefined
  status?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
}): Promise<PolicySummary[]> {
  const { data } = await apiClient.get<PolicySummary[]>('/policies', { params })
  return data
}

export async function getPolicyDetail(policyId: string): Promise<PolicyDetail> {
  const { data } = await apiClient.get<PolicyDetail>(
    `/policies/${encodeURIComponent(policyId)}`,
  )
  return data
}

export async function createPolicy(
  payload: PolicyCreateRequest,
): Promise<PolicyDetail> {
  const { data } = await apiClient.post<PolicyDetail>('/policies', payload)
  return data
}

export async function updatePolicy(
  policyId: string,
  payload: PolicyUpdateRequest,
): Promise<PolicyDetail> {
  const { data } = await apiClient.patch<PolicyDetail>(
    `/policies/${encodeURIComponent(policyId)}`,
    payload,
  )
  return data
}

export async function getPolicyClaims(
  policyId: string,
): Promise<PolicyLinkedClaim[]> {
  const { data } = await apiClient.get<PolicyLinkedClaim[]>(
    `/policies/${encodeURIComponent(policyId)}/claims`,
  )
  return data
}

export async function addPolicyCoverage(
  policyId: string,
  payload: PolicyCoverageCreateRequest,
): Promise<PolicyCoverage> {
  const { data } = await apiClient.post<PolicyCoverage>(
    `/policies/${encodeURIComponent(policyId)}/coverages`,
    payload,
  )
  return data
}

export async function removePolicyCoverage(
  policyId: string,
  coverageId: string,
): Promise<void> {
  await apiClient.delete(
    `/policies/${encodeURIComponent(policyId)}/coverages/${encodeURIComponent(coverageId)}`,
  )
}

export async function addPolicyExclusion(
  policyId: string,
  payload: PolicyExclusionCreateRequest,
): Promise<PolicyExclusion> {
  const { data } = await apiClient.post<PolicyExclusion>(
    `/policies/${encodeURIComponent(policyId)}/exclusions`,
    payload,
  )
  return data
}

export async function removePolicyExclusion(
  policyId: string,
  exclusionId: string,
): Promise<void> {
  await apiClient.delete(
    `/policies/${encodeURIComponent(policyId)}/exclusions/${encodeURIComponent(exclusionId)}`,
  )
}

export async function linkPolicyToClaim(
  policyId: string,
  claimId: string,
): Promise<PolicyClaimLinkResponse> {
  const { data } = await apiClient.post<PolicyClaimLinkResponse>(
    `/policies/${encodeURIComponent(policyId)}/link-claim`,
    { claim_id: claimId },
  )
  return data
}

export async function getPolicyClauses(
  policyId: string,
): Promise<PolicyClause[]> {
  const { data } = await apiClient.get<PolicyClause[]>(
    `/policies/documents/${encodeURIComponent(policyId)}/clauses`,
  )
  return data
}

export async function verifyPolicyClause(
  policyId: string,
  clauseId: string,
  verificationStatus: 'verified' | 'needs_review',
): Promise<PolicyClause> {
  const { data } = await apiClient.patch<PolicyClause>(
    `/policies/documents/${encodeURIComponent(policyId)}/clauses/${encodeURIComponent(clauseId)}/verification`,
    { verification_status: verificationStatus },
  )
  return data
}

export async function grantPolicyAccess(
  policyId: string,
  payload: { team_id?: string; claim_id?: string },
): Promise<unknown> {
  const { data } = await apiClient.post(
    `/policies/documents/${encodeURIComponent(policyId)}/access-grants`,
    payload,
  )
  return data
}

export async function retryPolicyEmbedding(policyId: string): Promise<unknown> {
  const { data } = await apiClient.post(
    `/policies/documents/${encodeURIComponent(policyId)}/retry-embedding`,
  )
  return data
}
