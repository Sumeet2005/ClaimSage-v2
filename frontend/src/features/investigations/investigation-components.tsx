import { useState } from 'react'
import { isAxiosError } from 'axios'
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Edit3,
  History,
  LoaderCircle,
  LockKeyhole,
  Mail,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  useEditFinding,
  useFindingEdits,
  useInvestigationNotifications,
  useSubmitInvestigationReview,
} from '@/features/investigations/use-investigations'
import type {
  FindingReference,
  InvestigationReview,
  InvestigationReport,
  ReviewDecision,
} from '@/types/investigations'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'
import { useAuth } from '@/features/auth/auth-context'

export function PermissionDenied({ message }: { message: string }) {
  return (
    <Card className="flex min-h-48 flex-col items-center justify-center px-6 py-8 text-center">
      <LockKeyhole aria-hidden="true" className="size-6 text-graphite-600" />
      <h2 className="mt-3 font-display text-base font-semibold text-graphite-900">
        Authorization required
      </h2>
      <p className="mt-1 max-w-lg text-sm leading-6 text-graphite-600">{message}</p>
    </Card>
  )
}

export function QueryError({
  error,
  fallback,
  onRetry,
  isRetrying,
}: {
  error: unknown
  fallback: string
  onRetry: () => void
  isRetrying: boolean
}) {
  const status = isAxiosError(error) ? error.response?.status : undefined
  if (status === 401 || status === 403 || status === 404) {
    return <PermissionDenied message={getApiErrorMessage(error, fallback)} />
  }
  return (
    <Card className="flex min-h-48 flex-col items-center justify-center px-6 py-8 text-center">
      <AlertCircle aria-hidden="true" className="size-6 text-graphite-600" />
      <h2 className="mt-3 font-display text-base font-semibold text-graphite-900">
        Information could not be loaded
      </h2>
      <p className="mt-1 max-w-lg text-sm leading-6 text-graphite-600">
        {getApiErrorMessage(error, fallback)}
      </p>
      <Button className="mt-4" disabled={isRetrying} onClick={onRetry} variant="outline">
        Try again
      </Button>
    </Card>
  )
}

export function StatusBadge({ value }: { value: string }) {
  return (
    <Badge className="capitalize" variant={value === 'failed' ? 'accent' : 'secondary'}>
      {value.replaceAll('_', ' ')}
    </Badge>
  )
}

function referenceLabel(reference: FindingReference) {
  const provenance = reference.provenance ?? {}
  const filename =
    typeof provenance['filename'] === 'string' ? provenance['filename'] : null
  const page =
    typeof provenance['page_number'] === 'number' ? provenance['page_number'] : null
  const version =
    typeof provenance['policy_version'] === 'string'
      ? provenance['policy_version']
      : null
  const clause =
    typeof provenance['clause_identifier'] === 'string'
      ? provenance['clause_identifier']
      : null
  const insurer =
    typeof provenance['insurer_name'] === 'string'
      ? provenance['insurer_name']
      : null
  const product =
    typeof provenance['product_name'] === 'string'
      ? provenance['product_name']
      : null
  const verification =
    typeof provenance['verification_status'] === 'string'
      ? provenance['verification_status']
      : null

  return (
    <li className="break-words rounded-lg bg-ivory-50 p-2 text-[11px] leading-5 text-graphite-700" key={`${reference.source_id}-${reference.source_kind ?? ''}`}>
      <span className="font-medium">
        {filename ?? reference.source_kind ?? 'Source'}
      </span>
      {page !== null && ` · Page ${page}`}
      {insurer && ` · ${insurer}`}
      {product && ` · ${product}`}
      {version && ` · Version ${version}`}
      {clause && ` · Clause ${clause}`}
      {verification && ` · ${verification.replaceAll('_', ' ')}`}
      <span className="block break-all font-mono text-graphite-500">
        {reference.source_id}
        {reference.resolved_from_retrieval === false && ' · source not resolved'}
      </span>
    </li>
  )
}

function FindingEditModal({
  finding,
  investigationId,
  onClose,
}: {
  finding: {
    id: string
    specialist: string
    finding_type: string
    finding_data: Record<string, unknown>
  }
  investigationId: string
  onClose: () => void
}) {
  const [editedDataText, setEditedDataText] = useState(() =>
    JSON.stringify(finding.finding_data, null, 2),
  )
  const [reason, setReason] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)

  const mutation = useEditFinding(investigationId, finding.id)

  const handleDataChange = (value: string) => {
    setEditedDataText(value)
    try {
      const parsed = JSON.parse(value)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('Finding data must be a valid JSON object.')
      } else {
        setParseError(null)
      }
    } catch (err) {
      setParseError((err as Error).message)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(editedDataText)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('Finding data must be a valid JSON object.')
        return
      }
    } catch (err) {
      setParseError((err as Error).message)
      return
    }

    if (reason.trim().length < 5) {
      return
    }

    mutation.mutate(
      {
        edited_data: parsed,
        reason: reason.trim(),
      },
      {
        onSuccess: () => {
          onClose()
        },
      },
    )
  }

  const isValid = !parseError && reason.trim().length >= 5

  return (
    <div
      aria-labelledby="edit-finding-title"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-graphite-950/60 p-4 backdrop-blur-xs"
      role="dialog"
    >
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-ivory-300 bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-ivory-200 pb-4">
          <div>
            <h3 className="font-display text-base font-semibold text-graphite-900" id="edit-finding-title">
              Edit Finding Revision
            </h3>
            <p className="mt-0.5 text-xs text-graphite-500">
              {finding.specialist.replaceAll('_', ' ')} · {finding.finding_type.replaceAll('_', ' ')}
            </p>
          </div>
          <button
            aria-label="Close dialog"
            className="rounded-lg p-1 text-graphite-400 hover:bg-ivory-100 hover:text-graphite-700"
            onClick={onClose}
            type="button"
          >
            <X className="size-5" />
          </button>
        </div>

        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <div className="rounded-xl border border-champagne/40 bg-champagne-light/30 p-3 text-xs text-graphite-700">
            <span className="font-semibold text-graphite-800">Immutable baseline: </span>
            The original AI finding remains preserved. Your revision will be saved as a versioned human adjustment with your identity and reason for audit compliance.
          </div>

          <div>
            <label className="block text-xs font-medium text-graphite-700" htmlFor="finding-data-editor">
              Revised finding data (JSON)
            </label>
            <textarea
              className="mt-1.5 min-h-48 w-full font-mono text-xs rounded-xl border border-ivory-300 bg-ivory-50 p-3 leading-5 text-graphite-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/40"
              disabled={mutation.isPending}
              id="finding-data-editor"
              onChange={(e) => handleDataChange(e.target.value)}
              value={editedDataText}
            />
            {parseError && (
              <p className="mt-1 text-xs text-rose-600" role="alert">
                JSON syntax error: {parseError}
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-graphite-700" htmlFor="finding-edit-reason">
                Revision reason <span className="text-rose-500">*</span>
              </label>
              <span className={`text-[11px] ${reason.trim().length >= 5 ? 'text-emerald-700' : 'text-graphite-400'}`}>
                {reason.trim().length} / 5 chars minimum
              </span>
            </div>
            <textarea
              className="mt-1.5 min-h-20 w-full rounded-xl border border-ivory-300 bg-white p-3 text-xs leading-5 text-graphite-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/40"
              disabled={mutation.isPending}
              id="finding-edit-reason"
              maxLength={2000}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this finding is being revised (e.g., verified active room rent rider endorsement #4)."
              value={reason}
            />
          </div>

          {mutation.isError && (
            <div className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700" role="alert">
              {getApiErrorMessage(mutation.error, 'Could not save finding revision.')}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 border-t border-ivory-200 pt-4">
            <Button disabled={mutation.isPending} onClick={onClose} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={!isValid || mutation.isPending} type="submit">
              {mutation.isPending && <LoaderCircle className="mr-2 size-3.5 animate-spin" />}
              Save revision
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function FindingItem({
  finding,
  investigationId,
  disabled = false,
}: {
  finding: {
    id: string
    specialist: string
    finding_type: string
    finding_data: Record<string, unknown>
    severity: string | null
    confidence: string | null
    evidence_references: FindingReference[]
    policy_references: FindingReference[]
  }
  investigationId?: string | undefined
  disabled?: boolean | undefined
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const editsQuery = useFindingEdits(investigationId ?? '', finding.id)
  const edits = editsQuery.data ?? []
  const latestEdit = edits[0]

  const references = [
    ...finding.evidence_references,
    ...finding.policy_references,
  ]

  return (
    <Card className="relative transition-all" key={finding.id}>
      <CardContent className="space-y-3 pt-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold capitalize text-emerald-dark">
                {finding.specialist.replaceAll('_', ' ')}
              </p>
              {edits.length > 0 && (
                <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-600/20">
                  <Edit3 className="size-3" />
                  Revised ({edits.length})
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] capitalize text-graphite-500">
              {finding.finding_type.replaceAll('_', ' ')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {finding.severity && <StatusBadge value={`${finding.severity} severity`} />}
            {finding.confidence && <StatusBadge value={`${finding.confidence} confidence`} />}
            {investigationId && (
              <Button
                className="h-7 text-xs"
                disabled={disabled}
                onClick={() => setIsEditing(true)}
                size="sm"
                variant="outline"
              >
                <Edit3 className="mr-1 size-3" />
                Edit finding
              </Button>
            )}
          </div>
        </div>

        {/* If human revisions exist, highlight the latest revision separately */}
        {latestEdit ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-1 border-b border-amber-200/60 pb-2">
              <span className="flex items-center gap-1 font-semibold text-amber-900">
                <ShieldCheck className="size-3.5 text-amber-700" />
                Latest human revision by {latestEdit.editor_name}
              </span>
              <span className="text-[11px] text-amber-800">
                {new Date(latestEdit.created_at).toLocaleString()}
              </span>
            </div>
            <p className="mt-2 text-xs italic text-amber-900">
              <span className="font-medium not-italic">Reason: </span>"{latestEdit.reason}"
            </p>
            <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-2.5 font-mono text-[11px] leading-5 text-graphite-900 ring-1 ring-amber-200">
              {JSON.stringify(latestEdit.edited_data, null, 2)}
            </pre>
          </div>
        ) : null}

        {/* Original AI Finding (Always preserved and displayed) */}
        <div>
          <span className="text-[11px] font-medium uppercase tracking-wider text-graphite-500">
            {latestEdit ? 'Original AI Finding (Immutable Baseline)' : 'AI-generated Finding Data'}
          </span>
          <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-ivory-50 p-3 text-xs leading-5 text-graphite-800">
            {JSON.stringify(finding.finding_data, null, 2)}
          </pre>
        </div>

        {/* Revision history collapsible if multiple edits exist */}
        {edits.length > 1 && (
          <div className="border-t border-ivory-200 pt-2">
            <button
              className="flex items-center gap-1 text-[11px] font-medium text-emerald-800 hover:text-emerald-900"
              onClick={() => setShowHistory((prev) => !prev)}
              type="button"
            >
              <History className="size-3" />
              {showHistory ? 'Hide earlier revision history' : `View all ${edits.length} revision records`}
              {showHistory ? <ChevronUp className="ml-1 size-3" /> : <ChevronDown className="ml-1 size-3" />}
            </button>
            {showHistory && (
              <div className="mt-2 space-y-2">
                {edits.map((edit, idx) => (
                  <div className="rounded-lg border border-ivory-200 bg-white p-2.5 text-xs" key={edit.id}>
                    <div className="flex items-center justify-between text-[11px] text-graphite-500">
                      <span>Revision #{edits.length - idx} by <strong className="text-graphite-800">{edit.editor_name}</strong></span>
                      <span>{new Date(edit.created_at).toLocaleString()}</span>
                    </div>
                    <p className="mt-1 text-xs text-graphite-700">
                      <span className="font-medium">Reason: </span>{edit.reason}
                    </p>
                    <pre className="mt-1.5 max-h-40 overflow-auto rounded bg-ivory-50 p-2 font-mono text-[10px] text-graphite-800">
                      {JSON.stringify(edit.edited_data, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {references.length > 0 ? (
          <section>
            <h4 className="mb-2 text-xs font-semibold text-graphite-800">
              Source provenance
            </h4>
            <ul className="space-y-1">
              {references.map((reference) => referenceLabel(reference))}
            </ul>
          </section>
        ) : (
          <p className="text-xs text-graphite-500">
            No source references were attached to this finding.
          </p>
        )}

        {isEditing && investigationId && (
          <FindingEditModal
            finding={finding}
            investigationId={investigationId}
            onClose={() => setIsEditing(false)}
          />
        )}
      </CardContent>
    </Card>
  )
}

export function FindingList({
  findings,
  investigationId,
  disabled = false,
}: {
  findings: Array<{
    id: string
    specialist: string
    finding_type: string
    finding_data: Record<string, unknown>
    severity: string | null
    confidence: string | null
    evidence_references: FindingReference[]
    policy_references: FindingReference[]
  }>
  investigationId?: string | undefined
  disabled?: boolean | undefined
}) {
  if (findings.length === 0) {
    return (
      <Card>
        <CardContent className="pt-5 text-sm text-graphite-600">
          No structured findings were persisted for this investigation.
        </CardContent>
      </Card>
    )
  }
  return (
    <div className="space-y-3">
      {findings.map((finding) => (
        <FindingItem
          disabled={disabled}
          finding={finding}
          investigationId={investigationId}
          key={finding.id}
        />
      ))}
    </div>
  )
}

export function InvestigationNotificationsSection({
  investigationId,
}: {
  investigationId: string
}) {
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const query = useInvestigationNotifications(investigationId)
  const notifications = query.data ?? []

  const handleCopyLink = async (id: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2500)
    } catch {
      // fallback
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-champagne-light text-graphite-800">
            <Mail aria-hidden="true" className="size-4" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <CardTitle>Customer Communications & Notifications</CardTitle>
              {notifications.length > 0 && (
                <Badge className="text-xs" variant="outline">
                  {notifications.length} item{notifications.length === 1 ? '' : 's'}
                </Badge>
              )}
            </div>
            <p className="text-xs text-graphite-600">
              Draft customer communications and employee delivery states. Email drafts require human approval before dispatch.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isPending ? (
          <div className="flex items-center justify-center py-6 text-xs text-graphite-500">
            <LoaderCircle className="mr-2 size-4 animate-spin" />
            Loading communications…
          </div>
        ) : query.isError ? (
          <div className="rounded-lg bg-rose-50 p-4 text-xs text-rose-700">
            {getApiErrorMessage(query.error, 'Communication drafts could not be loaded.')}
          </div>
        ) : notifications.length === 0 ? (
          <p className="py-4 text-center text-xs text-graphite-500">
            No notification drafts or email deliveries recorded for this run.
          </p>
        ) : (
          <div className="space-y-3">
            {notifications.map((item) => (
              <div
                className="rounded-xl border border-ivory-200 bg-white p-4 text-xs shadow-xs"
                key={item.id}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ivory-100 pb-3">
                  <div className="flex flex-wrap items-center gap-2">
                    {item.is_draft ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-600/30">
                        DRAFT · UNSENT
                      </span>
                    ) : (
                      <StatusBadge value={item.status} />
                    )}
                    <span className="font-semibold text-graphite-900">
                      {item.event_type.replaceAll('_', ' ')}
                    </span>
                  </div>
                  <span className="text-[11px] text-graphite-500">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </div>

                <div className="mt-3 space-y-2">
                  {item.recipient_email && (
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="font-medium text-graphite-700">Recipient:</span>
                      <span className="text-graphite-900">
                        {item.recipient_name ? `${item.recipient_name} (${item.recipient_email})` : item.recipient_email}
                      </span>
                    </div>
                  )}

                  {item.subject && (
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="font-medium text-graphite-700">Subject:</span>
                      <span className="font-medium text-graphite-900">{item.subject}</span>
                    </div>
                  )}

                  {item.message && (
                    <div className="mt-2">
                      <span className="text-[11px] font-medium text-graphite-500">Draft message content:</span>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-ivory-50 p-2.5 font-sans text-xs leading-5 text-graphite-800">
                        {item.message}
                      </pre>
                    </div>
                  )}

                  {item.secure_upload_url && (
                    <div className="mt-3 rounded-lg border border-emerald/30 bg-emerald-light/20 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <span className="text-xs font-semibold text-emerald-dark">Secure Document Upload Link</span>
                          <p className="text-[11px] text-graphite-600">
                            Single-use portal link generated for the policyholder.
                          </p>
                        </div>
                        <Button
                          className="h-7 bg-white text-xs hover:bg-emerald-light/40"
                          onClick={() => handleCopyLink(item.id, item.secure_upload_url!)}
                          size="sm"
                          variant="outline"
                        >
                          {copiedId === item.id ? (
                            <>
                              <Check className="mr-1 size-3 text-emerald-700" />
                              Copied!
                            </>
                          ) : (
                            <>
                              <Copy className="mr-1 size-3" />
                              Copy upload link
                            </>
                          )}
                        </Button>
                      </div>
                    </div>
                  )}

                  {item.is_draft && (
                    <p className="mt-2 text-[11px] italic text-graphite-500">
                      This customer draft is safely held in pending status. It has not been dispatched and cannot be automatically sent.
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ReportSections({ data }: { data: Record<string, unknown> }) {
  const fields = [
    ['observed_facts', 'Observed facts'],
    ['analyst_interpretations', 'Analyst interpretations'],
    ['hypotheses', 'Hypotheses'],
    ['conflicting_findings', 'Conflicting findings'],
    ['missing_information', 'Missing information'],
    ['source_inventory', 'Source document inventory'],
    ['missing_information_reconciliation', 'Missing-information reconciliation'],
  ] as const
  const isFallback = data['report_generation_mode'] === 'deterministic_fallback'
  return (
    <div className="space-y-3">
      {isFallback && (
        <div
          className="rounded-xl border border-amber-300 bg-amber-50/80 p-3.5 text-xs text-amber-950"
          role="status"
        >
          <p className="font-semibold">
            Deterministic Fallback Report (Not a Completed AI-Generated Report)
          </p>
          <p className="mt-1 leading-5 text-amber-900">
            Consolidated AI report synthesis was unavailable. This report was deterministically
            compiled from persisted specialist outputs and retrieved source evidence. Mandatory
            human review is required.
          </p>
        </div>
      )}
      {fields.map(([key, title]) => {
        const entries = data[key]
        if (!Array.isArray(entries) || entries.length === 0) return null
        return (
          <section key={key}>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
              {title}
            </h4>
            <div className="space-y-2">
              {entries.map((entry, index) => (
                <pre
                  className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-ivory-200 bg-white p-3 text-xs leading-5 text-graphite-800"
                  key={`${key}-${index}`}
                >
                  {JSON.stringify(entry, null, 2)}
                </pre>
              ))}
            </div>
          </section>
        )
      })}
      {Array.isArray(data['validation_warnings']) && data['validation_warnings'].length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-3">
          <h4 className="text-xs font-semibold text-amber-900">
            Validation warnings
          </h4>
          <ul className="mt-1.5 list-inside list-disc space-y-1 text-xs leading-5 text-amber-900">
            {data['validation_warnings'].map((warning, idx) => (
              <li key={`${idx}-${String(warning)}`}>{String(warning)}</li>
            ))}
          </ul>
        </section>
      )}
      {typeof data['evidence_scope_note'] === 'string' && (
        <p className="rounded-xl bg-ivory-50 p-3 text-xs leading-5 text-graphite-700">
          {data['evidence_scope_note']}
        </p>
      )}
      {Array.isArray(data['specialist_coverage']) && (
        <section>
          <h4 className="mb-2 text-xs font-semibold text-graphite-800">
            Specialist coverage
          </h4>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-ivory-50 p-3 text-xs leading-5 text-graphite-700">
            {JSON.stringify(data['specialist_coverage'], null, 2)}
          </pre>
        </section>
      )}
    </div>
  )
}

export function PersistentReport({ report }: { report: InvestigationReport }) {
  const isFallback =
    report.report_data?.['report_generation_mode'] === 'deterministic_fallback'
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Persistent investigation report</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {isFallback && (
              <Badge className="bg-amber-100 text-amber-900" variant="secondary">
                Deterministic Fallback
              </Badge>
            )}
            <StatusBadge value={report.status} />
          </div>
        </div>
        <p className="text-xs text-graphite-500">
          Updated {new Date(report.updated_at).toLocaleString()}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {report.report_data ? (
          <ReportSections data={report.report_data} />
        ) : (
          <p className="text-sm text-graphite-600">
            No report content is available. The persisted status and limitations
            below describe the outcome.
          </p>
        )}
        {report.limitations.length > 0 && (
          <section className="rounded-xl border border-champagne/50 bg-champagne-light/50 p-3">
            <h3 className="text-xs font-semibold text-graphite-800">
              Report limitations
            </h3>
            <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-graphite-700">
              {report.limitations.map((limitation, index) => (
                <li key={`${index}-${limitation}`}>{limitation}</li>
              ))}
            </ul>
          </section>
        )}
        <div className="flex items-start gap-2 rounded-xl border border-champagne/50 bg-champagne-light/50 p-3 text-xs leading-5 text-graphite-800">
          <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-dark" />
          <p>Human review is mandatory. This report does not determine claim approval, denial, settlement, or payment.</p>
        </div>
      </CardContent>
    </Card>
  )
}

const reviewOptions: Array<{ value: ReviewDecision; label: string; variant?: 'default' | 'secondary' | 'outline' | 'destructive' }> = [
  { value: 'approved', label: 'Approve report' },
  { value: 'needs_additional_documents', label: 'Request documents' },
  { value: 'returned_for_investigation', label: 'Return for investigation' },
  { value: 'escalated', label: 'Escalate' },
  { value: 'reviewed', label: 'Mark reviewed' },
  { value: 'needs_follow_up', label: 'Needs follow-up' },
]

export function ReviewActions({
  investigationId,
  disabled = false,
}: {
  investigationId: string
  disabled?: boolean
}) {
  const { employee } = useAuth()
  const isAdmin = employee?.role?.toLowerCase() === 'admin'
  const [notes, setNotes] = useState('')
  const mutation = useSubmitInvestigationReview(investigationId)
  return (
    <div className="space-y-3">
      {!isAdmin && (
        <div className="rounded-xl border border-champagne/40 bg-champagne-light/30 p-3 text-xs text-graphite-800">
          <p className="font-semibold text-graphite-900">Review Authority Notice</p>
          <p className="mt-0.5 text-graphite-600">
            Consequential investigation review decisions require an Administrator role. Claims Analysts may inspect findings, evidence citations, and submit finding edits.
          </p>
        </div>
      )}
      <label className="block text-xs font-medium text-graphite-700" htmlFor={`review-notes-${investigationId}`}>
        Review notes (optional)
      </label>
      <textarea
        className="min-h-20 w-full rounded-xl border border-ivory-300 bg-white px-3 py-2 text-sm text-graphite-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/30 disabled:opacity-50"
        disabled={!isAdmin || disabled || mutation.isPending}
        id={`review-notes-${investigationId}`}
        maxLength={4000}
        onChange={(event) => setNotes(event.target.value)}
        value={notes}
      />
      {mutation.isError && (
        <p className="text-xs text-graphite-800" role="alert">
          {getApiErrorMessage(mutation.error, 'The review could not be saved.')}
        </p>
      )}
      {mutation.isSuccess && (
        <p className="text-xs text-emerald-dark" role="status">
          Review status was recorded for {mutation.data.reviewer_name}.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {reviewOptions.map((option) => (
          <Button
            disabled={!isAdmin || disabled || mutation.isPending}
            key={option.value}
            onClick={() =>
              mutation.mutate({
                decision: option.value,
                notes: notes.trim() || null,
              })
            }
            size="sm"
            variant={option.value === 'escalated' ? 'outline' : 'secondary'}
          >
            {mutation.isPending && mutation.variables?.decision === option.value ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : null}
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export function ReviewHistory({
  reviews,
  isLoading,
  error,
  emptyMessage = 'No human review has been recorded.',
}: {
  reviews: InvestigationReview[] | undefined
  isLoading: boolean
  error: unknown
  emptyMessage?: string
}) {
  if (isLoading) {
    return <p className="text-sm text-graphite-500" role="status">Loading review history…</p>
  }
  if (error) {
    return (
      <p className="text-sm text-graphite-700" role="alert">
        {getApiErrorMessage(error, 'Review history could not be loaded.')}
      </p>
    )
  }
  if (!reviews?.length) {
    return <p className="text-sm text-graphite-500">{emptyMessage}</p>
  }
  return (
    <ol className="space-y-2">
      {reviews.map((review) => (
        <li className="rounded-xl border border-ivory-200 bg-white p-3" key={review.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium text-graphite-900">
              {review.reviewer_name}
            </span>
            <StatusBadge value={review.decision} />
          </div>
          <p className="mt-1 text-[11px] text-graphite-500">
            {new Date(review.created_at).toLocaleString()}
          </p>
          {review.notes && (
            <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-graphite-700">
              {review.notes}
            </p>
          )}
        </li>
      ))}
    </ol>
  )
}

export function QueryLoading({ label }: { label: string }) {
  return (
    <Card className="flex min-h-32 items-center justify-center gap-2 text-sm text-graphite-500" role="status">
      <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
      {label}
    </Card>
  )
}
