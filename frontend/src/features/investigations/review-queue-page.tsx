import { ArrowUpRight, ClipboardCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageContainer } from '@/components/layout/page-container'
import {
  QueryError,
  QueryLoading,
  ReviewActions,
  StatusBadge,
} from '@/features/investigations/investigation-components'
import { useReviewQueue } from '@/features/investigations/use-investigations'

export function ReviewQueuePage() {
  const query = useReviewQueue()
  const pendingRuns =
    query.data?.claims.flatMap(({ claim, investigations }) =>
      investigations
        .filter((investigation) => investigation.human_review_status === 'pending')
        .map((investigation) => ({ claim, investigation })),
    ) ?? []
  const failedClaims = query.data?.failedClaims ?? []

  return (
    <PageContainer
      description="Review persisted investigation reports for claims you are authorized to access."
      eyebrow="Human review"
      title="Review queue"
    >
      {query.isPending ? (
        <QueryLoading label="Loading authorized investigations…" />
      ) : query.isError ? (
        <QueryError
          error={query.error}
          fallback="The review queue could not be loaded."
          isRetrying={query.isFetching}
          onRetry={() => void query.refetch()}
        />
      ) : pendingRuns.length === 0 ? (
        <div className="space-y-4">
          {failedClaims.length > 0 && (
            <section
              aria-label="Claims with unavailable investigation history"
              className="rounded-xl border border-champagne-dark/30 bg-champagne-light p-4 text-sm text-graphite-800"
              role="status"
            >
              Could not load investigation history for{' '}
              {failedClaims
                .map(({ claimNumber, error }) => `${claimNumber}: ${error}`)
                .join(' ')}
              Other authorized claims remain available; retry to try these claims again.
            </section>
          )}
          <Card className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
            <ClipboardCheck aria-hidden="true" className="size-6 text-emerald-dark" />
            <h2 className="mt-3 font-display text-base font-semibold text-graphite-900">
              {query.data?.claims.length === 0 && failedClaims.length === 0
                ? 'No authorized claims available'
                : failedClaims.length > 0
                  ? 'Queue status is partial'
                  : 'Review queue is clear'}
            </h2>
            <p className="mt-1 max-w-lg text-sm leading-6 text-graphite-600">
              {query.data?.claims.length === 0 && failedClaims.length === 0
                ? 'Claims available to your account will be queried for persisted investigations.'
                : failedClaims.length > 0
                  ? 'Some claim histories could not be loaded. Retry the queue to check them again.'
                  : 'No pending investigation reviews were found among the claims visible to your account.'}
            </p>
            {failedClaims.length > 0 && (
              <Button
                className="mt-3"
                onClick={() => void query.refetch()}
                size="sm"
                variant="outline"
              >
                Retry queue
              </Button>
            )}
          </Card>
        </div>
      ) : (
        <div className="space-y-4">
          {failedClaims.length > 0 && (
            <section
              aria-label="Claims with unavailable investigation history"
              className="rounded-xl border border-champagne-dark/30 bg-champagne-light p-4 text-sm text-graphite-800"
              role="status"
            >
              Could not load investigation history for{' '}
              {failedClaims
                .map(({ claimNumber, error }) => `${claimNumber}: ${error}`)
                .join(' ')}
              Other authorized claims are shown below.
              <Button
                className="ml-3"
                onClick={() => void query.refetch()}
                size="sm"
                variant="outline"
              >
                Retry queue
              </Button>
            </section>
          )}
          <p className="text-sm text-graphite-600">
            {pendingRuns.length} investigation{pendingRuns.length === 1 ? '' : 's'} awaiting human review.
          </p>
          {pendingRuns.map(({ claim, investigation }) => (
            <Card key={investigation.id}>
              <CardHeader>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle>{claim.claim_number}</CardTitle>
                    <p className="mt-1 text-xs text-graphite-600">
                      {claim.claimant_name} · {claim.claim_type.replaceAll('_', ' ')}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge className="capitalize" variant="outline">
                        {investigation.claim_domain}
                      </Badge>
                      <StatusBadge value={investigation.status} />
                      {investigation.report_status && (
                        <StatusBadge value={`report ${investigation.report_status}`} />
                      )}
                      {investigation.evidence_sufficiency && (
                        <Badge className="capitalize" variant="outline">
                          Evidence {investigation.evidence_sufficiency.replaceAll('_', ' ')}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/investigations/${investigation.id}`}>
                      View details
                      <ArrowUpRight aria-hidden="true" />
                    </Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-[11px] text-graphite-500">
                  Started {new Date(investigation.created_at).toLocaleString()}
                </p>
                {investigation.report_status === 'unavailable' && (
                  <p className="rounded-lg bg-champagne-light p-3 text-xs leading-5 text-graphite-700">
                    The report is unavailable or incomplete. Review available findings and limitations; do not infer missing content.
                  </p>
                )}
                <ReviewActions
                  disabled={investigation.status === 'running'}
                  investigationId={investigation.id}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageContainer>
  )
}
