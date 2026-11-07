import { apiClient } from '@/lib/api-client'
import type { AuditTimelineResponse } from '@/types/investigations'

export interface AuditFilterParams {
  category?: string | undefined
  actorType?: string | undefined
  outcome?: string | undefined
  since?: string | undefined
  until?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
}

export async function getEnterpriseAuditEvents(
  params: AuditFilterParams = {},
): Promise<AuditTimelineResponse> {
  const { data } = await apiClient.get<AuditTimelineResponse>('/audit/events', {
    params: {
      event_category: params.category || undefined,
      actor_type: params.actorType || undefined,
      outcome: params.outcome || undefined,
      since: params.since || undefined,
      until: params.until || undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })
  return data
}
