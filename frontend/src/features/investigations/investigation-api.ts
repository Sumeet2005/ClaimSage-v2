import { apiClient } from '@/lib/api-client'
import type { Claim } from '@/types/claims'
import type {
  AuditTimelineResponse,
  FindingEdit,
  FindingEditRequest,
  InvestigationDetail,
  InvestigationNotification,
  InvestigationReport,
  InvestigationReview,
  InvestigationReviewRequest,
  InvestigationSummary,
} from '@/types/investigations'

export async function getClaimInvestigations(
  claimId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<InvestigationSummary[]> {
  const { data } = await apiClient.get<InvestigationSummary[]>(
    `/agent/claims/${encodeURIComponent(claimId)}/investigations`,
    {
      params: {
        limit: options.limit ?? 50,
        offset: options.offset ?? 0,
      },
    },
  )
  return data
}

export async function getInvestigation(
  investigationId: string,
): Promise<InvestigationDetail> {
  const { data } = await apiClient.get<InvestigationDetail>(
    `/agent/investigations/${encodeURIComponent(investigationId)}`,
  )
  return data
}

export async function getInvestigationReport(
  investigationId: string,
): Promise<InvestigationReport> {
  const { data } = await apiClient.get<InvestigationReport>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/report`,
  )
  return data
}

export async function getInvestigationReviews(
  investigationId: string,
): Promise<InvestigationReview[]> {
  const { data } = await apiClient.get<InvestigationReview[]>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/reviews`,
  )
  return data
}

export async function submitInvestigationReview(
  investigationId: string,
  request: InvestigationReviewRequest,
): Promise<InvestigationReview> {
  const { data } = await apiClient.post<InvestigationReview>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/reviews`,
    request,
  )
  return data
}

export async function editInvestigationFinding(
  investigationId: string,
  findingId: string,
  request: FindingEditRequest,
): Promise<FindingEdit> {
  const { data } = await apiClient.post<FindingEdit>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/findings/${encodeURIComponent(findingId)}/edits`,
    request,
  )
  return data
}

export async function getFindingEdits(
  investigationId: string,
  findingId: string,
): Promise<FindingEdit[]> {
  const { data } = await apiClient.get<FindingEdit[]>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/findings/${encodeURIComponent(findingId)}/edits`,
  )
  return data
}

export async function getInvestigationNotifications(
  investigationId: string,
): Promise<InvestigationNotification[]> {
  const { data } = await apiClient.get<InvestigationNotification[]>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/notifications`,
  )
  return data
}

export async function getInvestigationAuditTimeline(
  investigationId: string,
  limit: number = 50,
  offset: number = 0,
): Promise<AuditTimelineResponse> {
  const { data } = await apiClient.get<AuditTimelineResponse>(
    `/agent/investigations/${encodeURIComponent(investigationId)}/audit`,
    { params: { limit, offset } },
  )
  return data
}

export interface AuthorizedClaimInvestigations {
  claims: Array<{ claim: Claim; investigations: InvestigationSummary[] }>
  failedClaims: Array<{ claimNumber: string; error: string }>
}

export async function getAuthorizedClaimInvestigations(): Promise<AuthorizedClaimInvestigations> {
  const { data: claims } = await apiClient.get<Claim[]>('/claims')
  const results = await Promise.all(
    claims.map(async (claim) => {
      try {
        return {
          claim,
          investigations: await getAllClaimInvestigations(claim.id),
          error: null,
        }
      } catch {
        return {
          claim,
          investigations: null,
          error: 'Investigation history could not be loaded.',
        }
      }
    }),
  )
  return {
    claims: results.flatMap(({ claim, investigations }) =>
      investigations === null ? [] : [{
      claim,
      investigations,
      }],
    ),
    failedClaims: results
      .filter((result) => result.investigations === null)
      .map(({ claim, error }) => ({
        claimNumber: claim.claim_number,
        error: error ?? 'Investigation history could not be loaded.',
      })),
  }
}

async function getAllClaimInvestigations(
  claimId: string,
): Promise<InvestigationSummary[] | null> {
  const pageSize = 100
  const investigations: InvestigationSummary[] = []
  for (let offset = 0; ; offset += pageSize) {
    const page = await getClaimInvestigations(claimId, {
      limit: pageSize,
      offset,
    })
    investigations.push(...page)
    if (page.length < pageSize) return investigations
  }
}
