import { useMemo, useState } from 'react'
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Filter,
  Search,
  ShieldAlert,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageContainer } from '@/components/layout/page-container'
import {
  QueryError,
  QueryLoading,
  StatusBadge,
} from '@/features/investigations/investigation-components'
import { useReviewQueue } from '@/features/investigations/use-investigations'

export function InvestigationsPage() {
  const query = useReviewQueue()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [reviewFilter, setReviewFilter] = useState<string>('all')

  const allRuns = useMemo(() => {
    return (
      query.data?.claims.flatMap(({ claim, investigations }) =>
        investigations.map((investigation) => ({ claim, investigation })),
      ) ?? []
    )
  }, [query.data])

  const failedClaims = query.data?.failedClaims ?? []

  const stats = useMemo(() => {
    const total = allRuns.length
    const pendingReview = allRuns.filter(
      (r) => r.investigation.human_review_status === 'pending',
    ).length
    const completed = allRuns.filter(
      (r) => r.investigation.status === 'completed',
    ).length
    const incompleteOrFailed = allRuns.filter((r) =>
      ['incomplete', 'failed'].includes(r.investigation.status),
    ).length

    return { total, pendingReview, completed, incompleteOrFailed }
  }, [allRuns])

  const filteredRuns = useMemo(() => {
    return allRuns.filter(({ claim, investigation }) => {
      const matchesSearch =
        search === '' ||
        claim.claim_number.toLowerCase().includes(search.toLowerCase()) ||
        claim.claimant_name.toLowerCase().includes(search.toLowerCase()) ||
        investigation.id.toLowerCase().includes(search.toLowerCase())

      const matchesStatus =
        statusFilter === 'all' || investigation.status === statusFilter

      const matchesReview =
        reviewFilter === 'all' ||
        investigation.human_review_status === reviewFilter

      return matchesSearch && matchesStatus && matchesReview
    })
  }, [allRuns, search, statusFilter, reviewFilter])

  return (
    <PageContainer
      breadcrumbs={[
        { label: 'Workspace', href: '/' },
        { label: 'Investigations' },
      ]}
      description="Persistent agent investigation runs, verification checkpoints, and report provenance across authorized claims."
      eyebrow="AI Agent Operations"
      title="Investigations"
    >
      <div className="space-y-6">
        {/* Metric summary stat cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Total Investigations
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-graphite-900">
                  {stats.total}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-ivory-100 text-graphite-700">
                <Activity className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Pending Human Review
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-amber-700">
                  {stats.pendingReview}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-amber-50 text-amber-700">
                <Clock className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Fully Completed Runs
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-emerald-800">
                  {stats.completed}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-emerald-light/40 text-emerald-dark">
                <CheckCircle2 className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Incomplete / Limitations
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-rose-700">
                  {stats.incompleteOrFailed}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-rose-50 text-rose-700">
                <ShieldAlert className="size-5" />
              </span>
            </div>
          </Card>
        </div>

        {/* Filter and Search Bar */}
        <div className="flex flex-col gap-3 rounded-2xl border border-ivory-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-graphite-400" />
            <Input
              className="pl-9 text-xs"
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by claim number, claimant name, or run ID…"
              value={search}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-graphite-600">
              <Filter className="size-3.5" />
              <span>Status:</span>
              <select
                aria-label="Filter investigations by execution status"
                className="rounded-lg border border-ivory-200 bg-white px-2.5 py-1 text-xs text-graphite-800 focus:outline-none focus:ring-1 focus:ring-emerald"
                onChange={(e) => setStatusFilter(e.target.value)}
                value={statusFilter}
              >
                <option value="all">All statuses</option>
                <option value="running">Running</option>
                <option value="incomplete">Incomplete</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-graphite-600">
              <span>Review:</span>
              <select
                aria-label="Filter investigations by human review status"
                className="rounded-lg border border-ivory-200 bg-white px-2.5 py-1 text-xs text-graphite-800 focus:outline-none focus:ring-1 focus:ring-emerald"
                onChange={(e) => setReviewFilter(e.target.value)}
                value={reviewFilter}
              >
                <option value="all">All review states</option>
                <option value="pending">Pending review</option>
                <option value="approved">Approved</option>
                <option value="needs_additional_documents">Needs documents</option>
                <option value="returned_for_investigation">Returned</option>
                <option value="escalated">Escalated</option>
              </select>
            </div>
          </div>
        </div>

        {/* Query content */}
        {query.isPending ? (
          <QueryLoading label="Loading investigations workspace…" />
        ) : query.isError ? (
          <QueryError
            error={query.error}
            fallback="The investigations workspace could not be loaded."
            isRetrying={query.isFetching}
            onRetry={() => void query.refetch()}
          />
        ) : filteredRuns.length === 0 ? (
          <Card className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
            <Activity aria-hidden="true" className="size-6 text-graphite-400" />
            <h2 className="mt-3 font-display text-base font-semibold text-graphite-900">
              {allRuns.length === 0
                ? 'No investigations recorded'
                : 'No matching investigations found'}
            </h2>
            <p className="mt-1 max-w-lg text-sm leading-6 text-graphite-600">
              {allRuns.length === 0
                ? 'Investigations dispatched from authorized claim pages will appear here.'
                : 'Try adjusting your status or review filters.'}
            </p>
          </Card>
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
                Other authorized claims are listed below.
              </section>
            )}

            <div className="flex items-center justify-between text-xs text-graphite-500">
              <span>
                Showing {filteredRuns.length} of {allRuns.length} total run{allRuns.length === 1 ? '' : 's'}
              </span>
            </div>

            <div className="grid gap-3">
              {filteredRuns.map(({ claim, investigation }) => (
                <Card
                  className="transition-all hover:border-ivory-300 hover:shadow-xs"
                  key={investigation.id}
                >
                  <CardHeader className="pb-3">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            className="font-display text-base font-semibold text-graphite-900 hover:text-emerald-dark hover:underline"
                            to={`/claims/${claim.id}`}
                          >
                            {claim.claim_number}
                          </Link>
                          <span className="text-xs text-graphite-400">·</span>
                          <span className="text-xs font-medium text-graphite-700">
                            {claim.claimant_name}
                          </span>
                          <span className="text-xs text-graphite-400">·</span>
                          <span className="text-xs capitalize text-graphite-500">
                            {claim.claim_type.replaceAll('_', ' ')}
                          </span>
                        </div>

                        <p className="mt-1 font-mono text-[11px] text-graphite-400">
                          Run ID: {investigation.id}
                        </p>

                        <div className="mt-2.5 flex flex-wrap gap-2">
                          <Badge className="capitalize" variant="outline">
                            {investigation.claim_domain}
                          </Badge>
                          <StatusBadge value={investigation.status} />
                          <StatusBadge
                            value={`review: ${investigation.human_review_status}`}
                          />
                          {investigation.report_status && (
                            <StatusBadge
                              value={`report ${investigation.report_status}`}
                            />
                          )}
                          {investigation.evidence_sufficiency && (
                            <Badge className="capitalize" variant="outline">
                              Evidence{' '}
                              {investigation.evidence_sufficiency.replaceAll(
                                '_',
                                ' ',
                              )}
                            </Badge>
                          )}
                        </div>
                      </div>

                      <Button asChild size="sm" variant="outline">
                        <Link to={`/investigations/${investigation.id}`}>
                          View details
                          <ArrowUpRight aria-hidden="true" className="ml-1 size-3.5" />
                        </Link>
                      </Button>
                    </div>
                  </CardHeader>

                  <CardContent className="pt-0">
                    <div className="flex flex-wrap items-center justify-between border-t border-ivory-100 pt-3 text-[11px] text-graphite-500">
                      <div>
                        <span>Started: </span>
                        <span className="text-graphite-700">
                          {new Date(investigation.created_at).toLocaleString()}
                        </span>
                      </div>
                      {investigation.completed_at && (
                        <div>
                          <span>Completed: </span>
                          <span className="text-graphite-700">
                            {new Date(investigation.completed_at).toLocaleString()}
                          </span>
                        </div>
                      )}
                      <div>
                        <span>Current Stage: </span>
                        <span className="capitalize font-medium text-graphite-800">
                          {investigation.current_stage?.replaceAll('_', ' ') ??
                            'Finished'}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}
      </div>
    </PageContainer>
  )
}
