import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSearch,
  History,
  LoaderCircle,
  RefreshCw,
  Server,
  ShieldCheck,
  User,
  XCircle,
} from 'lucide-react'
import { getInvestigationAuditTimeline } from '@/features/investigations/investigation-api'
import { Link, useParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageContainer } from '@/components/layout/page-container'
import {
  FindingList,
  InvestigationNotificationsSection,
  PersistentReport,
  QueryError,
  QueryLoading,
  ReviewActions,
  ReviewHistory,
  StatusBadge,
} from '@/features/investigations/investigation-components'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'
import {
  useInvestigation,
  useInvestigationReport,
  useInvestigationReviews,
} from '@/features/investigations/use-investigations'
import type { InvestigationDetail } from '@/types/investigations'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatDate(value: string | null) {
  if (!value) return 'Not completed'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString()
}

function EvidenceSources({
  state,
  field,
  title,
}: {
  state: Record<string, unknown>
  field: 'claim_evidence' | 'policy_evidence' | 'repair_estimate_evidence'
  title: string
}) {
  const sourceFields = [
    ['Document ID', 'document_id'],
    ['Evidence chunk ID', 'chunk_id'],
    ['Insurer', 'insurer_name'],
    ['Product', 'product_name'],
    ['Policy identifier / UIN', 'policy_identifier'],
    ['Official source URL', 'source_url'],
    ['Policy version', 'policy_version'],
    ['Effective from', 'effective_from'],
    ['Effective to', 'effective_to'],
    ['Clause identifier', 'clause_identifier'],
    ['Clause ID', 'clause_id'],
    ['Verification status', 'verification_status'],
    ['Extraction method', 'extraction_method'],
  ] as const
  const evidence = state[field]
  if (!Array.isArray(evidence) || evidence.length === 0) return null

  // Deduplicate chunks by chunk_id
  const seenChunkIds = new Set<string>()
  const rawChunks = evidence.filter(isRecord).filter((source) => {
    const chunkId = typeof source['chunk_id'] === 'string' ? source['chunk_id'] : null
    if (!chunkId) return true
    if (seenChunkIds.has(chunkId)) return false
    seenChunkIds.add(chunkId)
    return true
  })

  // Group chunks by unique document_id (or filename fallback)
  const docMap = new Map<string, { documentId: string; filename: string; passages: Record<string, unknown>[] }>()
  for (const chunk of rawChunks) {
    const docId = typeof chunk['document_id'] === 'string' && chunk['document_id'].trim()
      ? (chunk['document_id'] as string)
      : typeof chunk['clause_id'] === 'string' && chunk['clause_id'].trim()
      ? (chunk['clause_id'] as string)
      : typeof chunk['filename'] === 'string' && chunk['filename'].trim()
      ? (chunk['filename'] as string)
      : `doc-${docMap.size}`
    const fn = typeof chunk['filename'] === 'string' ? (chunk['filename'] as string) : 'Retrieved Document'

    if (!docMap.has(docId)) {
      docMap.set(docId, {
        documentId: docId,
        filename: fn,
        passages: [],
      })
    }
    docMap.get(docId)!.passages.push(chunk)
  }

  const groupedDocs = Array.from(docMap.values())

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
        {title}
      </h3>
      <div className="space-y-3">
        {groupedDocs.map((doc, docIdx) => (
          <details
            className="rounded-xl border border-ivory-200 bg-white p-3.5"
            key={`${doc.documentId}-${docIdx}`}
            open={groupedDocs.length === 1}
          >
            <summary className="cursor-pointer text-xs font-semibold text-graphite-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald">
              <div className="inline-flex w-full items-center justify-between pr-2">
                <span>{doc.filename}</span>
                <span className="ml-2 rounded-full bg-ivory-100 px-2 py-0.5 text-[10px] font-medium text-graphite-600">
                  {doc.passages.length} {doc.passages.length === 1 ? 'passage' : 'passages'} retrieved
                </span>
              </div>
            </summary>
            {doc.documentId && doc.documentId !== doc.filename && (
              <p className="mt-1 break-all font-mono text-[11px] text-graphite-500">
                Document ID: {doc.documentId}
              </p>
            )}
            <div className="mt-3 space-y-2.5 border-t border-ivory-200 pt-3">
              {doc.passages.map((passage, pIdx) => (
                <div
                  key={`${String(passage['chunk_id'] ?? pIdx)}-${pIdx}`}
                  className="rounded-lg border border-ivory-100 bg-ivory-50/50 p-2.5"
                >
                  <div className="flex items-center justify-between text-[11px] font-medium text-graphite-700">
                    <span>
                      Passage {typeof passage['chunk_index'] === 'number' ? passage['chunk_index'] + 1 : pIdx + 1}
                      {typeof passage['page_number'] === 'number' && ` · Page ${passage['page_number']}`}
                    </span>
                    {typeof passage['similarity'] === 'number' && (
                      <span className="text-[10px] text-graphite-500 font-mono">
                        Similarity: {(passage['similarity'] as number).toFixed(3)}
                      </span>
                    )}
                  </div>
                  <dl className="mt-1.5 space-y-1 break-words text-[11px] leading-5 text-graphite-600">
                    {sourceFields.map(([label, key]) =>
                      key !== 'document_id' && typeof passage[key] === 'string' ? (
                        <div key={key}>
                          <dt className="inline font-medium">{label}: </dt>
                          <dd className="inline font-mono">{String(passage[key])}</dd>
                        </div>
                      ) : null,
                    )}
                  </dl>
                  {typeof passage['text'] === 'string' && (
                    <p className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap border-t border-ivory-200/60 pt-2 text-xs leading-5 text-graphite-700">
                      {String(passage['text'])}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  )
}

function InvestigationOverview({
  investigation,
}: {
  investigation: InvestigationDetail
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Investigation status</CardTitle>
            <p className="mt-1 break-all font-mono text-[11px] text-graphite-500">
              {investigation.id}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge className="capitalize" variant="outline">
              {investigation.claim_domain}
            </Badge>
            <StatusBadge value={investigation.status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-3 border-t border-ivory-200 pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-[11px] text-graphite-500">Human review</dt>
            <dd className="mt-1 text-sm font-medium capitalize text-graphite-800">
              {investigation.human_review_status.replaceAll('_', ' ')}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-graphite-500">Started</dt>
            <dd className="mt-1 text-sm text-graphite-800">
              {formatDate(investigation.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-graphite-500">Completed</dt>
            <dd className="mt-1 text-sm text-graphite-800">
              {formatDate(investigation.completed_at)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-graphite-500">Current stage</dt>
            <dd className="mt-1 text-sm capitalize text-graphite-800">
              {investigation.current_stage?.replaceAll('_', ' ') ?? 'Finished'}
            </dd>
          </div>
        </dl>
        {investigation.failure_type && (
          <p className="rounded-lg bg-champagne-light p-3 text-xs text-graphite-800" role="status">
            Execution ended with failure category: {investigation.failure_type}
          </p>
        )}
        <div>
          <h3 className="text-xs font-semibold text-graphite-700">Investigation task</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-graphite-800">
            {investigation.task}
          </p>
        </div>
        {investigation.status === 'running' && (
          <p className="text-xs text-graphite-600" role="status">
            This run is still in progress. Its persisted status refreshes automatically
            {investigation.current_stage
              ? ` while ${investigation.current_stage.replaceAll('_', ' ')} runs.`
              : '.'}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function ReviewPanel({
  investigation,
  investigationId,
}: {
  investigation: InvestigationDetail
  investigationId: string
}) {
  const reviewsQuery = useInvestigationReviews(investigationId)
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-champagne-light text-graphite-800">
            <ShieldCheck aria-hidden="true" className="size-4" />
          </span>
          <div>
            <CardTitle>Human review</CardTitle>
            <p className="mt-1 text-xs leading-5 text-graphite-600">
              Record review status only. Claim disposition and payment remain outside this workflow.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <ReviewActions
          disabled={investigation.status === 'running'}
          investigationId={investigationId}
        />
        <div className="border-t border-ivory-200 pt-4">
          <h3 className="mb-3 text-xs font-semibold text-graphite-800">
            Review history
          </h3>
          <ReviewHistory
            error={reviewsQuery.error}
            isLoading={reviewsQuery.isPending}
            reviews={reviewsQuery.data}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function InvestigationSignals({ state }: { state: Record<string, unknown> }) {
  const result = isRecord(state['result']) ? state['result'] : {}
  const statuses = [
    ['Policy retrieval', state['policy_retrieval_status']],
    ['Claim evidence retrieval', state['claim_evidence_retrieval_status']],
    ['Policy analysis', state['ai_analysis_status']],
    ['Evidence analysis', state['evidence_analysis_status']],
    ['Report generation', state['review_report_status']],
  ].filter((entry): entry is [string, string] => typeof entry[1] === 'string')
  const limitations = Array.isArray(result['limitations'])
    ? result['limitations'].filter(
        (value): value is string => typeof value === 'string',
      )
    : []
  const providerFailures = Array.isArray(result['provider_failures'])
    ? result['provider_failures'].filter(isRecord)
    : []

  if (!statuses.length && !limitations.length && !providerFailures.length) {
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analysis status and limitations</CardTitle>
        <p className="text-xs leading-5 text-graphite-600">
          AI analyses are preliminary and may be unavailable or incomplete. All
          findings require authenticated human review.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {statuses.length > 0 && (
          <dl className="flex flex-wrap gap-2">
            {statuses.map(([label, value]) => (
              <div
                className="flex items-center gap-2 rounded-lg bg-ivory-50 px-3 py-2"
                key={label}
              >
                <dt className="text-xs text-graphite-600">{label}</dt>
                <dd><StatusBadge value={value} /></dd>
              </div>
            ))}
          </dl>
        )}
        {providerFailures.length > 0 && (
          <section aria-label="Sanitized AI provider failures">
            <h3 className="text-xs font-semibold text-graphite-800">
              AI provider or analysis failures
            </h3>
            <ul className="mt-2 space-y-1 text-xs text-graphite-700">
              {providerFailures.map((failure, index) => (
                <li key={`${String(failure['stage'])}-${index}`}>
                  {typeof failure['stage'] === 'string'
                    ? failure['stage'].replaceAll('_', ' ')
                    : 'AI stage'}{' '}
                  ·{' '}
                  {typeof failure['category'] === 'string'
                    ? failure['category'].replaceAll('_', ' ')
                    : 'unavailable'}
                </li>
              ))}
            </ul>
          </section>
        )}
        {limitations.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-graphite-800">
              Investigation limitations
            </h3>
            <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-graphite-700">
              {limitations.map((limitation, index) => (
                <li key={`${index}-${limitation}`}>{limitation}</li>
              ))}
            </ul>
          </section>
        )}
      </CardContent>
    </Card>
  )
}


function InvestigationAuditTimeline({ investigationId }: { investigationId: string }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['investigation-audit-timeline', investigationId],
    queryFn: () => getInvestigationAuditTimeline(investigationId, 50, 0),
  })

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-ivory-200 text-graphite-700">
            <History className="size-5" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <CardTitle>Investigation Audit Trail</CardTitle>
              {data && (
                <Badge variant="outline" className="text-xs">
                  {data.total_count} events
                </Badge>
              )}
            </div>
            <p className="text-xs text-graphite-600">
              Complete execution timeline, AI agent actions, worker state changes, and reviews.
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="h-8 text-xs"
        >
          <RefreshCw className={`size-3.5 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-xs text-graphite-500">
            <LoaderCircle className="size-4 animate-spin mr-2" />
            Loading investigation audit events…
          </div>
        ) : error ? (
          <div className="rounded-lg bg-rose-50 p-4 text-xs text-rose-700">
            Failed to load investigation audit history.
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="py-6 text-center text-xs text-graphite-500">
            No audit events recorded for this investigation yet.
          </div>
        ) : (
          <div className="space-y-2.5">
            {data.items.map((event) => {
              const isExpanded = expandedId === event.id
              const hasMetadata =
                event.event_metadata && Object.keys(event.event_metadata).length > 0

              return (
                <div
                  key={event.id}
                  className="rounded-lg border border-ivory-200 bg-white p-3 text-xs transition-colors hover:border-ivory-300"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {getActorBadge(event.actor_type)}
                      <span className="font-semibold text-graphite-900">
                        {event.action}
                      </span>
                      <span className="rounded bg-ivory-200 px-1.5 py-0.5 text-[10px] uppercase font-mono text-graphite-700">
                        {event.event_category}
                      </span>
                      {getOutcomeBadge(event.outcome)}
                    </div>
                    <div className="flex items-center gap-2 text-graphite-500 text-[11px]">
                      <span>{new Date(event.created_at).toLocaleString()}</span>
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-graphite-600">
                    <div>
                      <span className="font-medium text-graphite-700">Actor: </span>
                      <span>{event.actor_name}</span>
                    </div>
                    {event.resource_type && (
                      <div>
                        <span className="font-medium text-graphite-700">Resource: </span>
                        <span>{event.resource_type}</span>
                        {event.resource_id && (
                          <span className="font-mono text-graphite-500 ml-1">
                            ({event.resource_id.slice(0, 8)}…)
                          </span>
                        )}
                      </div>
                    )}
                    {event.details && (
                      <div className="w-full text-graphite-700 mt-0.5">
                        {event.details}
                      </div>
                    )}
                  </div>

                  {hasMetadata && (
                    <div className="mt-2 pt-2 border-t border-ivory-100">
                      <button
                        type="button"
                        onClick={() => toggleExpand(event.id)}
                        className="flex items-center gap-1 text-[11px] font-medium text-emerald-700 hover:text-emerald-800"
                      >
                        {isExpanded ? (
                          <>
                            <ChevronUp className="size-3" />
                            Hide event metadata
                          </>
                        ) : (
                          <>
                            <ChevronDown className="size-3" />
                            View sanitized metadata
                          </>
                        )}
                      </button>
                      {isExpanded && (
                        <pre className="mt-2 max-h-48 overflow-auto rounded bg-graphite-900 p-2.5 font-mono text-[11px] text-emerald-300">
                          {JSON.stringify(event.event_metadata, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function InvestigationDetailPage() {
  const { investigationId = '' } = useParams()
  const query = useInvestigation(investigationId)
  const reportQuery = useInvestigationReport(investigationId)
  const investigation = query.data
  const reportNotFound =
    isAxiosError(reportQuery.error) && reportQuery.error.response?.status === 404

  return (
    <PageContainer
      actions={
        <Button asChild variant="outline">
          <Link to={investigation ? `/claims/${investigation.claim_id}` : '/claims'}>
            <ArrowLeft aria-hidden="true" />
            Back to claim
          </Link>
        </Button>
      }
      breadcrumbs={[
        { label: 'Workspace', href: '/' },
        { label: 'Claims', href: '/claims' },
        { label: 'Investigation' },
      ]}
      description="Persistent investigation state, findings, report provenance, and human review history."
      eyebrow="Investigation"
      title="Investigation detail"
    >
      <div className="space-y-4">
        {query.isPending ? (
          <QueryLoading label="Loading investigation…" />
        ) : query.isError ? (
          <QueryError
            error={query.error}
            fallback="Investigation details could not be loaded."
            isRetrying={query.isFetching}
            onRetry={() => void query.refetch()}
          />
        ) : investigation ? (
          <>
            <InvestigationOverview investigation={investigation} />
            <InvestigationSignals state={investigation.state_snapshot} />
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <span className="grid size-10 place-items-center rounded-xl bg-emerald-light text-emerald-dark">
                    <FileSearch aria-hidden="true" className="size-4" />
                  </span>
                  <CardTitle>AI-generated findings for human review</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <FindingList
                  disabled={investigation.status === 'running'}
                  findings={investigation.findings}
                  investigationId={investigation.id}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Retrieved source evidence</CardTitle>
                <p className="text-xs leading-5 text-graphite-600">
                  Source content and identifiers below are taken from the persisted investigation snapshot.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <EvidenceSources
                  field="claim_evidence"
                  state={investigation.state_snapshot}
                  title="Claim evidence"
                />
                <EvidenceSources
                  field="repair_estimate_evidence"
                  state={investigation.state_snapshot}
                  title="Repair estimate evidence"
                />
                <EvidenceSources
                  field="policy_evidence"
                  state={investigation.state_snapshot}
                  title="Policy passages and clause provenance"
                />
                {!['claim_evidence', 'repair_estimate_evidence', 'policy_evidence'].some(
                  (key) =>
                    Array.isArray(investigation.state_snapshot[key]) &&
                    (investigation.state_snapshot[key] as unknown[]).length > 0,
                ) && (
                  <p className="text-sm text-graphite-600">
                    No retrieved source passages were persisted for this run.
                  </p>
                )}
              </CardContent>
            </Card>
            {reportQuery.isPending ? (
              <QueryLoading label="Loading persistent report…" />
            ) : reportQuery.isError && !reportNotFound ? (
              <QueryError
                error={reportQuery.error}
                fallback="The persisted report could not be loaded."
                isRetrying={reportQuery.isFetching}
                onRetry={() => void reportQuery.refetch()}
              />
            ) : reportQuery.data ? (
              <PersistentReport report={reportQuery.data} />
            ) : (
              <Card>
                <CardContent className="pt-5 text-sm text-graphite-600">
                  {reportNotFound
                    ? 'A persistent report has not been created for this investigation.'
                    : getApiErrorMessage(reportQuery.error, 'No report is available yet.')}
                </CardContent>
              </Card>
            )}
            <InvestigationNotificationsSection investigationId={investigationId} />
            <ReviewPanel
              investigation={investigation}
              investigationId={investigationId}
            />
            <InvestigationAuditTimeline investigationId={investigationId} />
          </>
        ) : null}
      </div>
    </PageContainer>
  )
}
