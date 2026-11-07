import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  editInvestigationFinding,
  getAuthorizedClaimInvestigations,
  getClaimInvestigations,
  getFindingEdits,
  getInvestigation,
  getInvestigationNotifications,
  getInvestigationReport,
  getInvestigationReviews,
  submitInvestigationReview,
} from '@/features/investigations/investigation-api'
import type {
  FindingEditRequest,
  InvestigationReviewRequest,
} from '@/types/investigations'

export const claimInvestigationsQueryKey = (claimId: string) =>
  ['investigations', 'claim', claimId] as const

export const investigationQueryKey = (investigationId: string) =>
  ['investigations', 'detail', investigationId] as const

export const investigationReportQueryKey = (investigationId: string) =>
  ['investigations', 'report', investigationId] as const

export const investigationReviewsQueryKey = (investigationId: string) =>
  ['investigations', 'reviews', investigationId] as const

export const investigationNotificationsQueryKey = (investigationId: string) =>
  ['investigations', 'notifications', investigationId] as const

export const findingEditsQueryKey = (investigationId: string, findingId: string) =>
  ['investigations', investigationId, 'findings', findingId, 'edits'] as const

export const reviewQueueQueryKey = ['investigations', 'review-queue'] as const

export function useClaimInvestigations(claimId: string) {
  return useQuery({
    queryKey: claimInvestigationsQueryKey(claimId),
    queryFn: () => getClaimInvestigations(claimId),
    enabled: Boolean(claimId),
    refetchInterval: (query) =>
      query.state.data?.some((investigation) => investigation.status === 'running')
        ? 2000
        : false,
  })
}

export function useInvestigation(investigationId: string) {
  return useQuery({
    queryKey: investigationQueryKey(investigationId),
    queryFn: () => getInvestigation(investigationId),
    enabled: Boolean(investigationId),
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 2000 : false,
  })
}

export function useInvestigationReport(investigationId: string) {
  return useQuery({
    queryKey: investigationReportQueryKey(investigationId),
    queryFn: () => getInvestigationReport(investigationId),
    enabled: Boolean(investigationId),
    retry: (failureCount, error) => {
      const status = 'response' in error
        ? (error.response as { status?: number } | undefined)?.status
        : undefined
      return status !== 404 && failureCount < 1
    },
  })
}

export function useInvestigationReviews(investigationId: string) {
  return useQuery({
    queryKey: investigationReviewsQueryKey(investigationId),
    queryFn: () => getInvestigationReviews(investigationId),
    enabled: Boolean(investigationId),
  })
}

export function useInvestigationNotifications(investigationId: string) {
  return useQuery({
    queryKey: investigationNotificationsQueryKey(investigationId),
    queryFn: () => getInvestigationNotifications(investigationId),
    enabled: Boolean(investigationId),
  })
}

export function useFindingEdits(investigationId: string, findingId: string) {
  return useQuery({
    queryKey: findingEditsQueryKey(investigationId, findingId),
    queryFn: () => getFindingEdits(investigationId, findingId),
    enabled: Boolean(investigationId && findingId),
  })
}

export function useEditFinding(investigationId: string, findingId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: FindingEditRequest) =>
      editInvestigationFinding(investigationId, findingId, request),
    onSuccess: async (newEdit) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: findingEditsQueryKey(investigationId, findingId),
        }),
        queryClient.invalidateQueries({
          queryKey: investigationQueryKey(investigationId),
        }),
      ])
      queryClient.setQueryData(
        findingEditsQueryKey(investigationId, findingId),
        (current: typeof newEdit[] | undefined) => [
          newEdit,
          ...(current ?? []).filter((item) => item.id !== newEdit.id),
        ],
      )
    },
  })
}

export function useReviewQueue() {
  return useQuery({
    queryKey: reviewQueueQueryKey,
    queryFn: getAuthorizedClaimInvestigations,
  })
}

export function useSubmitInvestigationReview(investigationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: InvestigationReviewRequest) =>
      submitInvestigationReview(investigationId, request),
    onSuccess: async (review) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: investigationQueryKey(investigationId),
        }),
        queryClient.invalidateQueries({
          queryKey: investigationReviewsQueryKey(investigationId),
        }),
        queryClient.invalidateQueries({
          queryKey: ['investigations', 'claim'],
        }),
        queryClient.invalidateQueries({ queryKey: reviewQueueQueryKey }),
      ])
      queryClient.setQueryData(
        investigationReviewsQueryKey(investigationId),
        (current: typeof review[] | undefined) => [
          review,
          ...(current ?? []).filter((item) => item.id !== review.id),
        ],
      )
    },
  })
}
