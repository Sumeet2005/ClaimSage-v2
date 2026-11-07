import { useQuery } from '@tanstack/react-query'
import { getClaim } from '@/features/claims/claim-api'

export const claimDetailQueryKey = (claimId: string) =>
  ['claims', 'detail', claimId] as const

export function useClaimDetail(claimId: string) {
  return useQuery({
    queryKey: claimDetailQueryKey(claimId),
    queryFn: () => getClaim(claimId),
    enabled: Boolean(claimId),
  })
}
