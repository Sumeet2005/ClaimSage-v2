import { useQuery } from '@tanstack/react-query'
import { getClaims } from '@/features/claims/claims-api'

export const claimsQueryKey = ['claims'] as const

export function useClaims() {
  return useQuery({
    queryKey: claimsQueryKey,
    queryFn: getClaims,
  })
}
