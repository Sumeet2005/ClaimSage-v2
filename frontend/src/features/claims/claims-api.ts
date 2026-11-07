import { apiClient } from '@/lib/api-client'
import type { Claim } from '@/types/claims'
import type { CreateClaimPayload } from '@/features/claims/claim-api'

export async function getClaims(): Promise<Claim[]> {
  const { data } = await apiClient.get<Claim[]>('/claims')
  return data
}

export async function createClaim(payload: CreateClaimPayload): Promise<Claim> {
  const { data } = await apiClient.post<Claim>('/claims', payload)
  return data
}
