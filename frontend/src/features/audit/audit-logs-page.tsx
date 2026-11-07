import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Filter,
  History,
  LoaderCircle,
  RefreshCw,
  Search,
  Server,
  Shield,
  ShieldAlert,
  User,
  XCircle,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageContainer } from '@/components/layout/page-container'
import { getEnterpriseAuditEvents } from '@/features/audit/audit-api'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'

const PAGE_SIZE = 25

export function AuditLogsPage() {
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [actorTypeFilter, setActorTypeFilter] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const queryKey = [
    'audit-events',
    page,
    categoryFilter,
    actorTypeFilter,
    outcomeFilter,
  ]

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey,
    queryFn: () =>
      getEnterpriseAuditEvents({
        category: categoryFilter || undefined,
        actorType: actorTypeFilter || undefined,
        outcome: outcomeFilter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  })

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  const items = data?.items ?? []
  const totalCount = data?.total_count ?? 0
  const totalPages = Math.ceil(totalCount / PAGE_SIZE)

  // Filter items in view if local search text is entered
  const filteredItems = items.filter((item) => {
    if (!search) return true
    const term = search.toLowerCase()
    return (
      item.action.toLowerCase().includes(term) ||
      item.actor_name.toLowerCase().includes(term) ||
      (item.details && item.details.toLowerCase().includes(term)) ||
      (item.resource_id && item.resource_id.toLowerCase().includes(term))
    )
  })

  const getActorBadge = (type: string) => {
    switch (type) {
      case 'ai_agent':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-purple-50 px-2 py-0.5 text-[11px] font-medium text-purple-700 ring-1 ring-inset ring-purple-600/20">
            <Bot className="size-3" />
            AI Agent
          </span>
        )
      case 'employee':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 ring-1 ring-inset ring-blue-600/20">
            <User className="size-3" />
            Employee
          </span>
        )
      case 'system':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-700 ring-1 ring-inset ring-gray-600/20">
            <Server className="size-3" />
            System
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-500/20">
            {type}
          </span>
        )
    }
  }

  const getOutcomeBadge = (out: string) => {
    switch (out) {
      case 'success':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
            <CheckCircle2 className="size-3" />
            Success
          </span>
        )
      case 'failure':
      case 'error':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700 ring-1 ring-inset ring-rose-600/20">
            <XCircle className="size-3" />
            {out === 'error' ? 'Error' : 'Failed'}
          </span>
        )
      case 'denied':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20">
            <AlertCircle className="size-3" />
            Denied
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center rounded-md bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-500/20">
            {out}
          </span>
        )
    }
  }

  return (
    <PageContainer
      breadcrumbs={[
        { label: 'Administration', href: '/' },
        { label: 'Audit Logs' },
      ]}
      description="Immutable, append-only operational timeline tracking employee review actions, AI specialist calls, and system state transitions."
      eyebrow="Enterprise Governance"
      title="Audit Logs"
    >
      <div className="space-y-6">
        {/* Metric summary stat cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Total Logged Events
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-graphite-900">
                  {totalCount}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-ivory-100 text-graphite-700">
                <Shield className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Current Filter View
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-emerald-800">
                  {items.length}
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-emerald-light/40 text-emerald-dark">
                <History className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Security Redactions
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-graphite-800">
                  100%
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700">
                <CheckCircle2 className="size-5" />
              </span>
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-graphite-500">
                  Immutability Standard
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-graphite-800">
                  Append-Only
                </p>
              </div>
              <span className="grid size-10 place-items-center rounded-xl bg-champagne-light text-graphite-800">
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
              placeholder="Search action name, details, actor, or ID in current view…"
              value={search}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-graphite-600">
              <Filter className="size-3.5" />
              <span>Category:</span>
              <select
                aria-label="Filter by event category"
                className="rounded-lg border border-ivory-200 bg-white px-2 py-1 text-xs text-graphite-800 focus:outline-none focus:ring-1 focus:ring-emerald"
                onChange={(e) => {
                  setCategoryFilter(e.target.value)
                  setPage(0)
                }}
                value={categoryFilter}
              >
                <option value="">All categories</option>
                <option value="human_review">Human review</option>
                <option value="finding">Finding revisions</option>
                <option value="investigation">Investigation</option>
                <option value="claim">Claim lifecycle</option>
                <option value="evidence">Evidence</option>
                <option value="policy">Policy</option>
                <option value="auth">Authentication</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-graphite-600">
              <span>Actor:</span>
              <select
                aria-label="Filter by actor type"
                className="rounded-lg border border-ivory-200 bg-white px-2 py-1 text-xs text-graphite-800 focus:outline-none focus:ring-1 focus:ring-emerald"
                onChange={(e) => {
                  setActorTypeFilter(e.target.value)
                  setPage(0)
                }}
                value={actorTypeFilter}
              >
                <option value="">All actors</option>
                <option value="employee">Employee</option>
                <option value="ai_agent">AI Agent</option>
                <option value="system">System</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-graphite-600">
              <span>Outcome:</span>
              <select
                aria-label="Filter by outcome"
                className="rounded-lg border border-ivory-200 bg-white px-2 py-1 text-xs text-graphite-800 focus:outline-none focus:ring-1 focus:ring-emerald"
                onChange={(e) => {
                  setOutcomeFilter(e.target.value)
                  setPage(0)
                }}
                value={outcomeFilter}
              >
                <option value="">All outcomes</option>
                <option value="success">Success</option>
                <option value="failure">Failure</option>
                <option value="error">Error</option>
                <option value="denied">Denied</option>
              </select>
            </div>

            <Button
              className="h-8 text-xs"
              disabled={isFetching}
              onClick={() => void refetch()}
              size="sm"
              variant="outline"
            >
              <RefreshCw
                className={`mr-1 size-3.5 ${isFetching ? 'animate-spin' : ''}`}
              />
              Refresh
            </Button>
          </div>
        </div>

        {/* Content list */}
        {isLoading ? (
          <div className="flex min-h-48 items-center justify-center rounded-2xl border border-ivory-200 bg-white p-8 text-xs text-graphite-500">
            <LoaderCircle className="mr-2 size-4 animate-spin" />
            Loading enterprise audit history…
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-xs text-rose-700">
            {getApiErrorMessage(error, 'Audit events could not be loaded.')}
          </div>
        ) : filteredItems.length === 0 ? (
          <Card className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
            <Shield aria-hidden="true" className="size-6 text-graphite-400" />
            <h2 className="mt-3 font-display text-base font-semibold text-graphite-900">
              No audit events found
            </h2>
            <p className="mt-1 max-w-lg text-sm leading-6 text-graphite-600">
              No audit events matched the current filter criteria.
            </p>
          </Card>
        ) : (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-sm font-semibold">
                Event Activity Timeline ({totalCount} recorded)
              </CardTitle>
              <span className="text-xs text-graphite-500">
                Page {page + 1} of {Math.max(totalPages, 1)}
              </span>
            </CardHeader>
            <CardContent className="space-y-3">
              {filteredItems.map((event) => {
                const isExpanded = expandedId === event.id
                const hasMetadata =
                  event.event_metadata &&
                  Object.keys(event.event_metadata).length > 0

                return (
                  <div
                    className="rounded-xl border border-ivory-200 bg-white p-3.5 text-xs transition-colors hover:border-ivory-300"
                    key={event.id}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {getActorBadge(event.actor_type)}
                        <span className="font-semibold text-graphite-900">
                          {event.action}
                        </span>
                        <span className="rounded bg-ivory-200 px-1.5 py-0.5 font-mono text-[10px] uppercase text-graphite-700">
                          {event.event_category}
                        </span>
                        {getOutcomeBadge(event.outcome)}
                      </div>
                      <span className="text-[11px] text-graphite-500">
                        {new Date(event.created_at).toLocaleString()}
                      </span>
                    </div>

                    <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-graphite-600">
                      <div>
                        <span className="font-medium text-graphite-700">
                          Actor:{' '}
                        </span>
                        <span>{event.actor_name}</span>
                      </div>

                      {event.resource_type && (
                        <div>
                          <span className="font-medium text-graphite-700">
                            Resource:{' '}
                          </span>
                          <span>{event.resource_type}</span>
                          {event.resource_id && (
                            <span className="ml-1 font-mono text-graphite-500">
                              ({event.resource_id.slice(0, 8)}…)
                            </span>
                          )}
                        </div>
                      )}

                      {event.claim_id && (
                        <div>
                          <span className="font-medium text-graphite-700">
                            Claim:{' '}
                          </span>
                          <Link
                            className="font-mono text-emerald-dark hover:underline"
                            to={`/claims/${event.claim_id}`}
                          >
                            {event.claim_id.slice(0, 8)}…
                          </Link>
                        </div>
                      )}

                      {event.investigation_id && (
                        <div>
                          <span className="font-medium text-graphite-700">
                            Investigation:{' '}
                          </span>
                          <Link
                            className="font-mono text-emerald-dark hover:underline"
                            to={`/investigations/${event.investigation_id}`}
                          >
                            {event.investigation_id.slice(0, 8)}…
                          </Link>
                        </div>
                      )}
                    </div>

                    {event.details && (
                      <p className="mt-2 text-xs leading-5 text-graphite-700">
                        {event.details}
                      </p>
                    )}

                    {hasMetadata && (
                      <div className="mt-2.5 border-t border-ivory-100 pt-2">
                        <button
                          className="flex items-center gap-1 text-[11px] font-medium text-emerald-700 hover:text-emerald-800"
                          onClick={() => toggleExpand(event.id)}
                          type="button"
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp className="size-3" />
                              Hide sanitized metadata
                            </>
                          ) : (
                            <>
                              <ChevronDown className="size-3" />
                              View sanitized event metadata
                            </>
                          )}
                        </button>
                        {isExpanded && (
                          <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-graphite-900 p-3 font-mono text-[11px] leading-5 text-emerald-300">
                            {JSON.stringify(event.event_metadata, null, 2)}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}

              {/* Pagination controls */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t border-ivory-200 pt-4 text-xs">
                  <span className="text-graphite-500">
                    Showing {page * PAGE_SIZE + 1}–
                    {Math.min((page + 1) * PAGE_SIZE, totalCount)} of{' '}
                    {totalCount} events
                  </span>

                  <div className="flex items-center gap-2">
                    <Button
                      disabled={page === 0 || isFetching}
                      onClick={() => setPage((p) => Math.max(p - 1, 0))}
                      size="sm"
                      variant="outline"
                    >
                      <ChevronLeft className="mr-1 size-3.5" />
                      Previous
                    </Button>
                    <span className="px-2 text-graphite-600">
                      Page {page + 1} of {totalPages}
                    </span>
                    <Button
                      disabled={page >= totalPages - 1 || isFetching}
                      onClick={() => setPage((p) => p + 1)}
                      size="sm"
                      variant="outline"
                    >
                      Next
                      <ChevronRight className="ml-1 size-3.5" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  )
}
