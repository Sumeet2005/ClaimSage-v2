import { useState, type FormEvent } from 'react'
import { isAxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FileText,
  History,
  LoaderCircle,
  LockKeyhole,
  Mail,
  RefreshCw,
  Send,
  Server,
  ShieldCheck,
  Upload,
  User,
  XCircle,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageContainer } from '@/components/layout/page-container'
import { ClaimInvestigationHistory } from '@/features/investigations/claim-investigation-history'
import {
  claimInvestigationsQueryKey,
  useClaimInvestigations,
  useInvestigation,
} from '@/features/investigations/use-investigations'
import {
  approveCustomerEmail,
  createCustomerEmailDraft,
  createInvestigation,
  getClaimAuditTimeline,
  getClaimEmails,
  sendCustomerEmail,
  updateClaimPolicyMetadata,
  uploadClaimEvidence,
} from '@/features/claims/claim-api'
import { getSpecialistResults } from '@/features/claims/specialist-status'
import {
  claimDetailQueryKey,
  useClaimDetail,
} from '@/features/claims/use-claim-detail'
import type {
  ClaimEvidenceUploadResponse,
  InvestigationResponse,
  ReviewReportItem,
} from '@/types/claim-workspace'
import type { Claim } from '@/types/claims'

const MAX_PDF_SIZE = 20 * 1024 * 1024

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function errorMessage(error: unknown, fallback: string) {
  if (isAxiosError<{ detail?: unknown }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (error.response?.status === 401) {
      return 'Your session is no longer authorized. Sign in again to continue.'
    }
    if (error.response?.status === 403) {
      return 'You are not authorized to access this claim.'
    }
    if (error.response?.status === 404) {
      return 'This claim was not found or is not available to your account.'
    }
    if (error.response?.status === 413) {
      return 'The PDF exceeds the 20 MiB upload limit.'
    }
    if (error.response?.status === 415) {
      return 'Only PDF documents are supported.'
    }
    if (error.response?.status === 409) {
      return 'This evidence document already exists for the claim.'
    }
    if (!error.response) {
      return 'Unable to reach ClaimSage. Check your connection and try again.'
    }
  }
  return fallback
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function formatCalendarDate(value: string | null) {
  if (!value) return 'Not recorded'
  const date = new Date(`${value}T12:00:00`)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function displayLabel(value: string) {
  return value.replaceAll('_', ' ')
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function parseReportItem(value: unknown): ReviewReportItem | null {
  if (!isRecord(value)) return null
  const { statement, explanation, source_basis, limitation } = value
  if (
    typeof statement !== 'string' ||
    typeof explanation !== 'string' ||
    typeof source_basis !== 'string' ||
    (limitation !== null && typeof limitation !== 'string')
  ) {
    return null
  }

  const sources = Array.isArray(value['sources'])
    ? value['sources'].filter(
        (source): source is Record<string, unknown> =>
          isRecord(source) &&
          typeof source['evidence_id'] === 'string' &&
          typeof source['document_id'] === 'string' &&
          typeof source['filename'] === 'string' &&
          typeof source['page_number'] === 'number',
      ).map((source) => ({
        evidence_id: source['evidence_id'] as string,
        document_id: source['document_id'] as string,
        filename: source['filename'] as string,
        page_number: source['page_number'] as number,
      }))
    : []
  const supportingQuotes = Array.isArray(value['supporting_quotes'])
    ? value['supporting_quotes'].filter(
        (quote): quote is Record<string, unknown> =>
          isRecord(quote) &&
          typeof quote['evidence_id'] === 'string' &&
          typeof quote['quote'] === 'string',
      ).map((quote) => ({
        evidence_id: quote['evidence_id'] as string,
        quote: quote['quote'] as string,
      }))
    : []
  const analystReferences = Array.isArray(value['analyst_output_references'])
    ? value['analyst_output_references'].filter(
        (reference): reference is Record<string, unknown> =>
          isRecord(reference) &&
          typeof reference['specialist'] === 'string' &&
          typeof reference['output_path'] === 'string' &&
          typeof reference['finding_text'] === 'string',
      ).map((reference) => ({
        specialist: reference['specialist'] as string,
        output_path: reference['output_path'] as string,
        finding_text: reference['finding_text'] as string,
      }))
    : []

  return {
    statement,
    explanation,
    source_basis,
    limitation,
    supporting_evidence_ids: stringArray(value['supporting_evidence_ids']),
    supporting_quotes: supportingQuotes,
    sources,
    analyst_output_references: analystReferences,
  }
}

function ClaimOverview({ claim }: { claim: Claim }) {
  const details = [
    { label: 'Claimant', value: claim.claimant_name },
    { label: 'Claim type', value: displayLabel(claim.claim_type) },
    ...(claim.policy_identifier
      ? [{ label: 'Policy identifier', value: claim.policy_identifier }]
      : []),
    ...(claim.insurer_name
      ? [{ label: 'Insurer', value: claim.insurer_name }]
      : []),
    ...(claim.product_name
      ? [{ label: 'Product', value: claim.product_name }]
      : []),
    { label: 'Status', value: displayLabel(claim.status) },
    { label: 'Created', value: formatDate(claim.created_at) },
    { label: 'Loss date', value: formatCalendarDate(claim.loss_date) },
  ]

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-dark">
              Claim overview
            </p>
            <CardTitle className="mt-1 text-xl">{claim.claim_number}</CardTitle>
          </div>
          <Badge variant="secondary">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-emerald" />
            <span className="capitalize">{displayLabel(claim.status)}</span>
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-5 border-t border-ivory-200 pt-5 sm:grid-cols-2 lg:grid-cols-4">
          {details.map((item) => (
            <div className="min-w-0" key={item.label}>
              <dt className="text-xs font-medium text-graphite-500">
                {item.label}
              </dt>
              <dd className="mt-1 break-words text-sm font-medium text-graphite-900">
                {item.label === 'Created' ? (
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarDays aria-hidden="true" className="size-3.5 text-graphite-500" />
                    {item.value}
                  </span>
                ) : item.label === 'Policy identifier' ? (
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    <span>{item.value}</span>
                    <Link
                      to={`/policies?search=${encodeURIComponent(claim.policy_identifier ?? '')}`}
                      className="inline-flex items-center gap-0.5 text-xs font-semibold text-emerald-dark hover:text-emerald hover:underline"
                      title="View in Policy Workspace"
                    >
                      <ShieldCheck className="size-3" />
                      View
                    </Link>
                  </span>
                ) : (
                  item.value
                )}
              </dd>
            </div>
          ))}
        </dl>
        <ClaimPolicyMetadataForm claim={claim} />
        <div className="mt-5 border-t border-ivory-200 pt-4">
          <h3 className="text-xs font-medium text-graphite-500">Summary</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-graphite-800">
            {claim.summary || 'No summary was provided for this claim.'}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

function ClaimPolicyMetadataForm({ claim }: { claim: Claim }) {
  const queryClient = useQueryClient()
  const [policyIdentifier, setPolicyIdentifier] = useState(
    claim.policy_identifier ?? '',
  )
  const [insurerName, setInsurerName] = useState(claim.insurer_name ?? '')
  const [productName, setProductName] = useState(claim.product_name ?? '')
  const [lossDate, setLossDate] = useState(claim.loss_date ?? '')
  const [verifiedAgainstSource, setVerifiedAgainstSource] = useState(false)
  const isHealthClaim = claim.claim_type.trim().toLowerCase() === 'health'
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        policy_identifier: policyIdentifier.trim(),
        loss_date: lossDate,
        verified_against_source: true,
        ...(insurerName.trim()
          ? { insurer_name: insurerName.trim() }
          : {}),
        ...(productName.trim()
          ? { product_name: productName.trim() }
          : {}),
      } satisfies Parameters<typeof updateClaimPolicyMetadata>[1]
      return updateClaimPolicyMetadata(claim.id, payload)
    },
    onSuccess: (updatedClaim) => {
      queryClient.setQueryData(claimDetailQueryKey(claim.id), updatedClaim)
    },
  })

  function submitMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !policyIdentifier.trim() ||
      !lossDate ||
      (isHealthClaim && (!insurerName.trim() || !productName.trim())) ||
      !verifiedAgainstSource ||
      mutation.isPending
    ) {
      return
    }
    mutation.mutate()
  }

  return (
    <div className="mt-5 border-t border-ivory-200 pt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-graphite-900">
          Policy metadata verification
        </h3>
        <Link
          to={claim.policy_identifier ? `/policies?search=${encodeURIComponent(claim.policy_identifier)}` : '/policies'}
          className="inline-flex items-center gap-1 text-xs font-medium text-emerald-dark hover:underline"
        >
          <ShieldCheck className="size-3.5" />
          Open Policy Workspace
        </Link>
      </div>
      <p className="mt-1 text-xs leading-5 text-graphite-600">
        Confirm the policy identifier and loss date against claim source
        documentation. Health policy retrieval also requires matching insurer
        and product metadata.
      </p>
      <form className="mt-3 space-y-3" onSubmit={submitMetadata}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="claim-policy-identifier">Policy identifier</Label>
            <Input
              autoComplete="off"
              id="claim-policy-identifier"
              maxLength={150}
              onChange={(event) => setPolicyIdentifier(event.target.value)}
              required
              value={policyIdentifier}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="claim-loss-date">Loss date</Label>
            <Input
              id="claim-loss-date"
              onChange={(event) => setLossDate(event.target.value)}
              required
              type="date"
              value={lossDate}
            />
          </div>
          {isHealthClaim && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="claim-insurer-name">Insurer</Label>
                <Input
                  autoComplete="organization"
                  id="claim-insurer-name"
                  maxLength={150}
                  onChange={(event) => setInsurerName(event.target.value)}
                  required
                  value={insurerName}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="claim-product-name">Policy product</Label>
                <Input
                  autoComplete="off"
                  id="claim-product-name"
                  maxLength={200}
                  onChange={(event) => setProductName(event.target.value)}
                  required
                  value={productName}
                />
              </div>
            </>
          )}
        </div>
        <label className="flex items-start gap-2 text-xs leading-5 text-graphite-700">
          <input
            checked={verifiedAgainstSource}
            className="mt-1 accent-emerald"
            onChange={(event) =>
              setVerifiedAgainstSource(event.target.checked)
            }
            type="checkbox"
          />
          I verified these details against the claim source documentation.
        </label>
        {mutation.isError && (
          <p className="text-sm text-graphite-800" role="alert">
            {errorMessage(mutation.error, 'Policy metadata could not be saved. Please try again.')}
          </p>
        )}
        {mutation.isSuccess && (
          <p className="text-sm text-emerald-dark" role="status">
            Policy metadata was saved and recorded as verified.
          </p>
        )}
        <Button
          disabled={
            !policyIdentifier.trim() ||
            !lossDate ||
            (isHealthClaim &&
              (!insurerName.trim() || !productName.trim())) ||
            !verifiedAgainstSource ||
            mutation.isPending
          }
          type="submit"
          variant="outline"
        >
          {mutation.isPending ? 'Saving…' : 'Save verified policy metadata'}
        </Button>
      </form>
    </div>
  )
}

function ClaimLoading() {
  return (
    <div aria-label="Loading claim" className="space-y-4" role="status">
      <span className="sr-only">Loading claim details</span>
      <Card className="h-56 animate-pulse bg-ivory-100" />
      <Card className="h-64 animate-pulse bg-ivory-100" />
    </div>
  )
}

function ClaimLoadError({
  error,
  onRetry,
  isRetrying,
}: {
  error: unknown
  onRetry: () => void
  isRetrying: boolean
}) {
  const status = isAxiosError(error) ? error.response?.status : undefined
  const unauthorized = status === 401 || status === 403
  const heading =
    status === 404
      ? 'Claim unavailable'
      : unauthorized
        ? 'Authorization required'
        : 'Claim details could not be loaded'

  return (
    <Card className="flex min-h-60 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-2xl bg-champagne-light text-graphite-700">
        {unauthorized ? (
          <LockKeyhole aria-hidden="true" className="size-5" />
        ) : (
          <AlertCircle aria-hidden="true" className="size-5" />
        )}
      </span>
      <h2 className="mt-4 font-display text-base font-semibold text-graphite-900">
        {heading}
      </h2>
      <p className="mt-1 max-w-md text-sm leading-6 text-graphite-600">
        {errorMessage(error, 'Claim details could not be loaded. Please try again.')}
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {status !== 404 && (
          <Button
            disabled={isRetrying}
            onClick={onRetry}
            variant="outline"
          >
            <RefreshCw
              aria-hidden="true"
              className={isRetrying ? 'animate-spin' : ''}
            />
            Try again
          </Button>
        )}
        <Button asChild variant="secondary">
          <Link to="/claims">
            <ArrowLeft aria-hidden="true" />
            Back to claims
          </Link>
        </Button>
      </div>
    </Card>
  )
}

function ProviderFailures({ failures }: { failures: unknown[] }) {
  const safeFailures = failures.filter(
    (failure): failure is Record<string, unknown> =>
      isRecord(failure) &&
      typeof failure['stage'] === 'string' &&
      typeof failure['category'] === 'string',
  )
  if (safeFailures.length === 0) return null

  return (
    <section className="rounded-lg border border-champagne bg-champagne-light p-3">
      <h4 className="text-xs font-semibold text-graphite-800">
        Provider stage failures
      </h4>
      <ul className="mt-2 space-y-1 text-xs text-graphite-700">
        {safeFailures.map((failure, index) => (
          <li key={`${failure['stage']}-${index}`}>
            {displayLabel(String(failure['stage']))}: {displayLabel(String(failure['category']))}
            {typeof failure['status_code'] === 'number' &&
              ` (HTTP ${failure['status_code']})`}
            {typeof failure['provider_code'] === 'string' &&
              ` — ${failure['provider_code']}`}
            {typeof failure['provider_retry_hint'] === 'boolean' &&
              ` — Provider retry hint: ${failure['provider_retry_hint'] ? 'yes' : 'no'}`}
            {typeof failure['retry_after_seconds'] === 'number' &&
              ` — Retry-After: ${failure['retry_after_seconds']}s`}
          </li>
        ))}
      </ul>
    </section>
  )
}

function HumanReviewNotice() {
  return (
    <div
      className="flex gap-3 rounded-2xl border border-champagne/45 bg-champagne-light/60 p-4 text-graphite-800"
      role="note"
    >
      <ShieldCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-emerald-dark" />
      <div>
        <p className="text-sm font-semibold">Human review is required</p>
        <p className="mt-1 text-xs leading-5 text-graphite-700">
          AI output is assistive and must be reviewed by a person. It does not
          approve or deny claims, confirm fraud, determine liability or
          coverage, or authorize payment.
        </p>
      </div>
    </div>
  )
}

function UploadSection({ claimId }: { claimId: string }) {
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const mutation = useMutation({
    mutationFn: (selectedFile: File) =>
      uploadClaimEvidence(claimId, selectedFile, setProgress),
    onSuccess: () => setProgress(100),
  })

  function chooseFile(selectedFile: File | undefined) {
    mutation.reset()
    setProgress(0)
    setFileError(null)
    setFile(selectedFile ?? null)
    if (!selectedFile) return

    const isPdfName = selectedFile.name.toLocaleLowerCase().endsWith('.pdf')
    const hasPdfType =
      !selectedFile.type || selectedFile.type === 'application/pdf'
    if (!isPdfName || !hasPdfType) {
      setFileError('Choose a PDF document.')
      setFile(null)
    } else if (selectedFile.size > MAX_PDF_SIZE) {
      setFileError('The selected PDF exceeds the 20 MiB limit.')
      setFile(null)
    }
  }

  function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (file && !mutation.isPending && !fileError) mutation.mutate(file)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-light text-emerald-dark">
            <Upload aria-hidden="true" className="size-4" />
          </span>
          <div>
            <CardTitle>Upload evidence</CardTitle>
            <p className="mt-1 text-xs leading-5 text-graphite-600">
              Add a PDF to this claim. The backend processes it and returns its
              document status; this workspace does not provide evidence browsing.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={submitUpload}>
          <Label className="block" htmlFor="claim-evidence-file">
            PDF document
          </Label>
          <Input
            accept=".pdf,application/pdf"
            aria-describedby="evidence-file-help evidence-file-error"
            className="h-auto min-h-11 cursor-pointer py-2 file:mr-3 file:rounded-lg file:border-0 file:bg-emerald-light file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-emerald-dark"
            disabled={mutation.isPending}
            id="claim-evidence-file"
            onChange={(event) => chooseFile(event.target.files?.[0])}
            type="file"
          />
          <p className="text-xs text-graphite-500" id="evidence-file-help">
            PDF only · Maximum size 20 MiB
          </p>
          {fileError && (
            <p className="text-xs font-medium text-graphite-800" id="evidence-file-error" role="alert">
              {fileError}
            </p>
          )}
          {file && (
            <p className="break-all text-xs text-graphite-600">
              Selected: {file.name} ({(file.size / (1024 * 1024)).toFixed(2)} MiB)
            </p>
          )}
          {mutation.isPending && (
            <div aria-live="polite">
              <div className="flex justify-between text-xs text-graphite-600">
                <span>Uploading evidence…</span>
                <span>{progress}%</span>
              </div>
              <progress
                aria-label="Evidence upload progress"
                className="mt-2 h-2 w-full accent-emerald"
                max={100}
                value={progress}
              />
            </div>
          )}
          {mutation.isError && (
            <p className="text-sm text-graphite-800" role="alert">
              {errorMessage(mutation.error, 'The evidence upload failed. Please try again.')}
            </p>
          )}
          {mutation.isSuccess && (
            <UploadSuccess response={mutation.data} />
          )}
          <Button
            className="w-full sm:w-auto"
            disabled={!file || mutation.isPending || Boolean(fileError)}
            type="submit"
          >
            {mutation.isPending ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <Upload aria-hidden="true" />
            )}
            {mutation.isPending ? 'Uploading…' : 'Upload PDF'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function UploadSuccess({ response }: { response: ClaimEvidenceUploadResponse }) {
  return (
    <div
      className="rounded-xl border border-emerald/20 bg-emerald-light/55 p-3 text-xs text-graphite-800"
      role="status"
    >
      <p className="flex items-center gap-2 font-semibold text-emerald-dark">
        <CheckCircle2 aria-hidden="true" className="size-4" />
        Evidence upload processed
      </p>
      <dl className="mt-2 grid gap-1 sm:grid-cols-2">
        <div><dt className="inline text-graphite-500">File: </dt><dd className="inline break-all">{response.filename}</dd></div>
        <div><dt className="inline text-graphite-500">Status: </dt><dd className="inline">{response.status}</dd></div>
        <div><dt className="inline text-graphite-500">Chunks: </dt><dd className="inline">{response.chunk_count}</dd></div>
        <div><dt className="inline text-graphite-500">Document ID: </dt><dd className="inline break-all">{response.document_id}</dd></div>
      </dl>
    </div>
  )
}


function formatInvestigationStage(stage: string | null | undefined): string {
  if (!stage) return 'Queued'
  const stages: Record<string, string> = {
    queued: 'Queued for processing',
    starting: 'Starting investigation',
    investigate: 'Extracting claim facts',
    retrieve_claim_evidence: 'Retrieving claim evidence',
    supervisor: 'Supervisor planning & delegation',
    intake_agent: 'Intake document analysis',
    evidence_analyst: 'Evidence verification',
    policy_analyst: 'Policy compliance review',
    repair_estimate_analyst: 'Repair estimate analysis',
    risk_anomaly_agent: 'Risk & anomaly detection',
    review_report: 'Synthesizing final review report',
  }
  return stages[stage] ?? stage.replaceAll('_', ' ')
}
function InvestigationSection({
  claimId,
  claimType,
}: {
  claimId: string
  claimType: string
}) {
  const [task, setTask] = useState('')
  const [repairEstimateDocumentId, setRepairEstimateDocumentId] = useState('')
  const [activeInvestigationId, setActiveInvestigationId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  // Monitor claim investigations to detect any already running investigation
  const claimInvestigationsQuery = useClaimInvestigations(claimId)
  const runningFromHistory = claimInvestigationsQuery.data?.find(
    (inv) => inv.status === 'running',
  )
  const effectiveInvestigationId = activeInvestigationId ?? runningFromHistory?.id ?? null

  const activeInvestigationQuery = useInvestigation(effectiveInvestigationId ?? '')

  const mutation = useMutation({
    mutationFn: (submission: {
      task: string
      repairEstimateDocumentId?: string
    }) =>
      createInvestigation(
        claimId,
        submission.task,
        submission.repairEstimateDocumentId,
      ),
    onSuccess: async (data) => {
      if (data?.investigation_id) {
        setActiveInvestigationId(data.investigation_id)
      }
      await queryClient.invalidateQueries({
        queryKey: claimInvestigationsQueryKey(claimId),
      })
    },
  })
  const trimmedTask = task.trim()
  const isMotorClaim = ['auto', 'motor'].includes(
    claimType.trim().toLowerCase(),
  )

  const isExecuting = mutation.isPending || activeInvestigationQuery.data?.status === 'running'

  function submitInvestigation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmedTask || isExecuting) return
    const estimateDocumentId = repairEstimateDocumentId.trim()
    mutation.mutate({
      task: trimmedTask,
      ...(estimateDocumentId
        ? { repairEstimateDocumentId: estimateDocumentId }
        : {}),
    })
  }

  // Build response from active investigation query if completed or incomplete
  const activeData = activeInvestigationQuery.data
  let completedResponse: InvestigationResponse | null = null
  if (activeData && (activeData.status === 'completed' || activeData.status === 'incomplete')) {
    const snapshot = activeData.state_snapshot || {}
    completedResponse = {
      investigation_id: activeData.id,
      execution_status: activeData.status,
      status: activeData.status,
      claim_facts: (snapshot['claim_facts'] as Record<string, unknown>) ?? null,
      result: (snapshot['result'] as Record<string, unknown>) ?? null,
      error: null,
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-champagne-light text-graphite-800">
            <FileText aria-hidden="true" className="size-4" />
          </span>
          <div>
            <CardTitle>AI investigation</CardTitle>
            <p className="mt-1 text-xs leading-5 text-graphite-600">
              Submit a task for this claim. The investigation is performed
              asynchronously by autonomous specialist agents against the authorized claim.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={submitInvestigation}>
          <Label className="block" htmlFor="investigation-task">
            Investigation task
          </Label>
          <textarea
            aria-describedby="investigation-task-help"
            className="min-h-28 w-full resize-y rounded-xl border border-ivory-300 bg-white px-3 py-2.5 text-sm text-graphite-900 shadow-sm transition-colors placeholder:text-graphite-400 hover:border-graphite-400/70 focus-visible:border-emerald focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={isExecuting}
            id="investigation-task"
            maxLength={1000}
            onChange={(event) => setTask(event.target.value)}
            placeholder="Describe what you need reviewed…"
            required
            value={task}
          />
          <p className="text-xs text-graphite-500" id="investigation-task-help">
            Required · 1–1000 characters
          </p>
          {isMotorClaim && (
            <div className="space-y-1.5">
              <Label className="block" htmlFor="repair-estimate-document-id">
                Repair estimate document ID (optional)
              </Label>
              <Input
                autoComplete="off"
                disabled={isExecuting}
                id="repair-estimate-document-id"
                maxLength={36}
                onChange={(event) =>
                  setRepairEstimateDocumentId(event.target.value)
                }
                placeholder="Paste the ID returned when the estimate was uploaded"
                value={repairEstimateDocumentId}
              />
              <p className="text-xs text-graphite-500">
                Leave blank to automatically resolve the uploaded repair estimate
                PDF for this motor claim, or paste a specific document ID.
              </p>
            </div>
          )}

          {mutation.isError && (
            <p className="text-sm text-graphite-800" role="alert">
              {errorMessage(mutation.error, 'The investigation could not be started. Please try again.')}
            </p>
          )}

          <Button disabled={!trimmedTask || isExecuting} type="submit">
            {isExecuting ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <FileText aria-hidden="true" />
            )}
            {isExecuting ? 'Investigating…' : 'Run investigation'}
          </Button>
        </form>

        {activeData?.status === 'running' && (
          <div className="mt-5 rounded-xl border border-emerald/20 bg-champagne-light/60 p-4" role="status">
            <div className="flex items-center gap-3">
              <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-emerald shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold text-graphite-900">
                    Investigation in progress…
                  </p>
                  <Badge variant="outline" className="text-xs capitalize font-medium">
                    {formatInvestigationStage(activeData.current_stage)}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-graphite-600">
                  AI specialist agents are analyzing the claim and policy evidence in the background. Results will appear automatically when complete.
                </p>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-ivory-200/80 pt-2 text-xs text-graphite-500">
              <span>Current stage: <strong>{formatInvestigationStage(activeData.current_stage)}</strong></span>
              <Link
                to={`/investigations/${activeData.id}`}
                className="font-medium text-emerald hover:underline"
              >
                Open detailed view →
              </Link>
            </div>
          </div>
        )}

        {activeData?.status === 'failed' && (
          <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4" role="alert">
            <div className="flex items-start gap-3">
              <AlertCircle className="size-5 text-red-600 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-red-900">Investigation execution failed</p>
                <p className="mt-1 text-xs text-red-700">
                  {activeData.failure_type
                    ? `Error category: ${activeData.failure_type}`
                    : 'The background investigation failed. Please check the investigation history or retry.'}
                </p>
                <Button
                  className="mt-3"
                  size="sm"
                  variant="outline"
                  onClick={() => setActiveInvestigationId(null)}
                >
                  Dismiss & retry
                </Button>
              </div>
            </div>
          </div>
        )}

        {completedResponse && (
          <InvestigationResults response={completedResponse} />
        )}
      </CardContent>
    </Card>
  )
}

function InvestigationResults({ response }: { response: InvestigationResponse }) {
  const result = response.result
  const report = result
    ? (isRecord(result['review_report'])
        ? result['review_report']
        : isRecord(result['fallback_report'])
          ? result['fallback_report']
          : null)
    : null
  const isDeterministicFallback =
    report?.['report_generation_mode'] === 'deterministic_fallback' ||
    Boolean(result && !isRecord(result['review_report']) && isRecord(result['fallback_report']))
  const reportHasHumanReview = report?.['human_review_required'] === true

  return (
    <div className="mt-6 space-y-4 border-t border-ivory-200 pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-graphite-900">
          Investigation results
        </h3>
        <Badge variant="accent">For human review</Badge>
        <Badge
          variant={response.execution_status === 'completed' ? 'outline' : 'secondary'}
        >
          Execution {displayLabel(response.execution_status)}
        </Badge>
      </div>
      {response.execution_status !== 'completed' && (
        <p className="rounded-lg bg-champagne-light p-3 text-xs text-graphite-800" role="status">
          This investigation did not complete all required stages. Available
          results and limitations are retained for human review.
        </p>
      )}
      {result ? (
        <>
          {response.investigation_id && (
            <Button asChild size="sm" variant="outline">
              <Link to={`/investigations/${response.investigation_id}`}>
                Open persisted investigation
              </Link>
            </Button>
          )}
          {typeof result['review_report_status'] === 'string' && (
            <p className="text-xs text-graphite-600">
              Review report:{' '}
              <span className="capitalize">
                {isDeterministicFallback
                  ? 'Deterministic Fallback Report (AI synthesis unavailable)'
                  : displayLabel(result['review_report_status'])}
              </span>
            </p>
          )}
          {report && reportHasHumanReview ? (
            <ReviewReportView isDeterministicFallback={isDeterministicFallback} report={report} />
          ) : report ? (
            <p className="text-sm text-graphite-800" role="alert">
              The returned report did not confirm mandatory human review and is
              not displayed. Review the investigation with a qualified person.
            </p>
          ) : (
            <p className="text-sm text-graphite-600">
              No review report was included in this response. Available
              specialist results are shown below.
            </p>
          )}
          <SpecialistResults result={result} />
          <EvidenceResults result={result} />
          {Array.isArray(result['limitations']) && result['limitations'].length > 0 && (
            <StringList title="Investigation limitations" values={result['limitations']} />
          )}
          {Array.isArray(result['provider_failures']) && (
            <ProviderFailures failures={result['provider_failures']} />
          )}
        </>
      ) : (
        <p className="text-sm text-graphite-600">
          The investigation response did not include a result.
        </p>
      )}
      <HumanReviewNotice />
    </div>
  )
}

const REPORT_SECTIONS = [
  ['observed_facts', 'Observed facts'],
  ['analyst_interpretations', 'Analyst interpretations'],
  ['hypotheses', 'Hypotheses'],
  ['conflicting_findings', 'Conflicting findings'],
  ['missing_information', 'Missing information'],
] as const

function ReviewReportView({
  report,
  isDeterministicFallback = false,
}: {
  report: Record<string, unknown>
  isDeterministicFallback?: boolean
}) {
  const isFallback =
    isDeterministicFallback ||
    report['report_generation_mode'] === 'deterministic_fallback'
  return (
    <section aria-label="Review report" className="space-y-4">
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
            constructed from persisted specialist outputs and retrieved source evidence without
            guessing or inferring unsupported facts. Mandatory human review is required.
          </p>
        </div>
      )}
      <div className="rounded-xl border border-ivory-200 bg-ivory-50 p-4">
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          {typeof report['overall_status'] === 'string' && (
            <p className="text-graphite-700">
              Report status: <span className="font-semibold capitalize">{displayLabel(report['overall_status'])}</span>
            </p>
          )}
          {typeof report['report_generation_mode'] === 'string' && (
            <p className="text-graphite-700">
              Generation mode:{' '}
              <span className="font-semibold capitalize">
                {displayLabel(report['report_generation_mode'])}
              </span>
            </p>
          )}
          {typeof report['report_completeness'] === 'string' && (
            <p className="text-graphite-700">
              Completeness:{' '}
              <span className="font-semibold capitalize">
                {displayLabel(report['report_completeness'])}
              </span>
            </p>
          )}
          {typeof report['policy_verification_status'] === 'string' && (
            <p className="text-graphite-700">
              Policy verification:{' '}
              <span className="font-semibold capitalize">
                {displayLabel(report['policy_verification_status'])}
              </span>
            </p>
          )}
          {typeof report['evidence_retrieval_status'] === 'string' && (
            <p className="text-graphite-700">
              Evidence retrieval: <span className="font-semibold capitalize">{displayLabel(report['evidence_retrieval_status'])}</span>
            </p>
          )}
        </div>
        {typeof report['evidence_scope_note'] === 'string' && (
          <p className="mt-3 text-xs leading-5 text-graphite-600">{report['evidence_scope_note']}</p>
        )}
      </div>
      {REPORT_SECTIONS.map(([key, title]) => (
        <ReportItemSection key={key} items={report[key]} title={title} />
      ))}
      <StringList
        title="Validation warnings"
        values={report['validation_warnings']}
      />
      <StringList
        title="Evidence retrieval limitations"
        values={report['evidence_retrieval_limitations']}
      />
      <SpecialistCoverage values={report['specialist_coverage']} />
    </section>
  )
}

function ReportItemSection({
  items,
  title,
}: {
  items: unknown
  title: string
}) {
  if (!Array.isArray(items) || items.length === 0) return null

  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
        {title}
      </h4>
      <div className="space-y-2">
        {items.map((item, index) => {
          const parsed = parseReportItem(item)
          return parsed ? (
            <ReportItem item={parsed} key={`${title}-${index}`} />
          ) : null
        })}
      </div>
    </section>
  )
}

function ReportItem({ item }: { item: ReviewReportItem }) {
  return (
    <article className="rounded-xl border border-ivory-200 bg-white p-3.5">
      <p className="text-sm font-medium leading-5 text-graphite-900">{item.statement}</p>
      <p className="mt-1 text-xs leading-5 text-graphite-600">{item.explanation}</p>
      {item.sources.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-ivory-200 pt-2">
          {item.sources.map((source, index) => (
            <li className="break-words text-[11px] text-graphite-600" key={`${source.evidence_id}-${index}`}>
              Source: {source.filename}, page {source.page_number} · Evidence ID{' '}
              <code>{source.evidence_id}</code>
            </li>
          ))}
        </ul>
      )}
      {item.supporting_quotes.map((quote, index) => (
        <blockquote
          className="mt-2 border-l-2 border-champagne pl-3 text-xs italic leading-5 text-graphite-700"
          key={`${quote.evidence_id}-${index}`}
        >
          “{quote.quote}”
        </blockquote>
      ))}
      {item.analyst_output_references.map((reference, index) => (
        <p className="mt-2 text-[11px] leading-5 text-graphite-600" key={`${reference.specialist}-${reference.output_path}-${index}`}>
          Analyst reference ({displayLabel(reference.specialist)} · {reference.output_path}):{' '}
          {reference.finding_text}
        </p>
      ))}
      {item.limitation && (
        <p className="mt-2 text-xs leading-5 text-graphite-700">
          Limitation: {item.limitation}
        </p>
      )}
    </article>
  )
}

function StringList({ title, values }: { title: string; values: unknown }) {
  if (!Array.isArray(values)) return null
  const strings = values.filter((value): value is string => typeof value === 'string')
  if (strings.length === 0) return null

  return (
    <section className="rounded-xl border border-ivory-200 bg-white p-3.5">
      <h4 className="text-xs font-semibold text-graphite-800">{title}</h4>
      <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-graphite-600">
        {strings.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}
      </ul>
    </section>
  )
}

function SpecialistCoverage({ values }: { values: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null

  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
        Specialist coverage
      </h4>
      <div className="space-y-2">
        {values.filter(isRecord).map((specialist, index) => (
          <div className="rounded-xl border border-ivory-200 bg-white p-3" key={`${String(specialist['specialist'])}-${index}`}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-medium text-graphite-800">
                {typeof specialist['specialist'] === 'string'
                  ? displayLabel(specialist['specialist'])
                  : 'Specialist'}
              </span>
              <Badge variant="outline">
                {typeof specialist['status'] === 'string'
                  ? displayLabel(specialist['status'])
                  : 'Status unavailable'}
              </Badge>
            </div>
            {typeof specialist['analysis_included'] === 'boolean' && (
              <p className="mt-1 text-[11px] text-graphite-500">
                Analysis {specialist['analysis_included'] ? 'included' : 'not included'}
              </p>
            )}
            <StringList
              title="Coverage limitations"
              values={specialist['limitations']}
            />
          </div>
        ))}
      </div>
    </section>
  )
}

function SpecialistResults({ result }: { result: Record<string, unknown> }) {
  const outputs = getSpecialistResults(result)
  if (outputs.length === 0) return null
  const providerFailures = Array.isArray(result['provider_failures'])
    ? result['provider_failures'].filter(isRecord)
    : []

  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
        Specialist results
      </h4>
      <div className="space-y-2">
        {outputs.map(({ field, title, status, output }) => {
          const matchingFailure = providerFailures.find(
            (failure) => failure['stage'] === field,
          )
          return (
            <details className="rounded-xl border border-ivory-200 bg-white p-3" key={field}>
              <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 text-sm font-medium text-graphite-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald">
                {title}
                <Badge variant="secondary">
                  {typeof status === 'string' ? displayLabel(status) : 'Status unavailable'}
                </Badge>
              </summary>
              {output == null ? (
                <div className="mt-3 space-y-1 text-xs text-graphite-600">
                  <p>No specialist output was returned.</p>
                  {matchingFailure && (
                    <p className="text-graphite-700">
                      Provider failure: {displayLabel(String(matchingFailure['category'] ?? 'unavailable'))}
                      {typeof matchingFailure['status_code'] === 'number' &&
                        ` (HTTP ${matchingFailure['status_code']})`}
                      {typeof matchingFailure['provider_code'] === 'string' &&
                        ` — ${matchingFailure['provider_code']}`}
                      {typeof matchingFailure['retry_after_seconds'] === 'number' &&
                        ` · Retry-After: ${matchingFailure['retry_after_seconds']}s`}
                    </p>
                  )}
                </div>
              ) : (
                <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-ivory-50 p-3 text-[11px] leading-5 text-graphite-700">
                  {JSON.stringify(output, null, 2)}
                </pre>
              )}
            </details>
          )
        })}
      </div>
    </section>
  )
}

function EvidenceResults({ result }: { result: Record<string, unknown> }) {
  const evidenceGroups = [
    ['claim_evidence', 'Claim evidence'],
    ['policy_evidence', 'Policy evidence'],
    ['repair_estimate_evidence', 'Repair estimate evidence'],
  ] as const
  const available = evidenceGroups.filter(
    ([field]) => Array.isArray(result[field]) && result[field].length > 0,
  )
  if (available.length === 0) return null

  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-graphite-700">
        Retrieved evidence in this investigation
      </h4>
      <p className="mb-2 text-xs leading-5 text-graphite-600">
        These are the evidence passages returned with this investigation, not
        a separate evidence library.
      </p>
      <div className="space-y-4">
        {available.map(([field, title]) => {
          const rawItems = (result[field] as unknown[]).filter(isRecord)
          const seenChunkIds = new Set<string>()
          const uniqueItems = rawItems.filter((source) => {
            const chunkId = typeof source['chunk_id'] === 'string' ? source['chunk_id'] : null
            if (!chunkId) return true
            if (seenChunkIds.has(chunkId)) return false
            seenChunkIds.add(chunkId)
            return true
          })

          const docMap = new Map<string, { documentId: string; filename: string; passages: Record<string, unknown>[] }>()
          for (const item of uniqueItems) {
            const docId = typeof item['document_id'] === 'string' && item['document_id'].trim()
              ? (item['document_id'] as string)
              : typeof item['clause_id'] === 'string' && item['clause_id'].trim()
              ? (item['clause_id'] as string)
              : typeof item['filename'] === 'string' && item['filename'].trim()
              ? (item['filename'] as string)
              : `doc-${docMap.size}`
            const fn = typeof item['filename'] === 'string' ? (item['filename'] as string) : 'Retrieved Document'

            if (!docMap.has(docId)) {
              docMap.set(docId, {
                documentId: docId,
                filename: fn,
                passages: [],
              })
            }
            docMap.get(docId)!.passages.push(item)
          }
          const groupedDocs = Array.from(docMap.values())

          return (
            <div key={field}>
              <h5 className="mb-2 text-xs font-medium text-graphite-700">{title}</h5>
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
                      {doc.passages.map((item, index) => (
                        <div
                          key={`${String(item['chunk_id'])}-${index}`}
                          className="rounded-lg border border-ivory-100 bg-ivory-50/50 p-2.5"
                        >
                          <div className="flex items-center justify-between text-[11px] font-medium text-graphite-700">
                            <span>
                              Passage {typeof item['chunk_index'] === 'number' ? item['chunk_index'] + 1 : index + 1}
                              {typeof item['page_number'] === 'number' ? ` · Page ${item['page_number']}` : ''}
                            </span>
                            {typeof item['similarity'] === 'number' && (
                              <span className="text-[10px] text-graphite-500 font-mono">
                                Similarity: {(item['similarity'] as number).toFixed(3)}
                              </span>
                            )}
                          </div>
                          <dl className="mt-1.5 space-y-1 text-[11px] text-graphite-600">
                            {typeof item['chunk_id'] === 'string' && (
                              <div className="break-all"><dt className="inline font-medium">Chunk ID: </dt><dd className="inline font-mono">{item['chunk_id']}</dd></div>
                            )}
                            {typeof item['policy_version'] === 'string' && (
                              <div><dt className="inline font-medium">Policy version: </dt><dd className="inline">{item['policy_version']}</dd></div>
                            )}
                            {typeof item['clause_identifier'] === 'string' && (
                              <div><dt className="inline font-medium">Clause: </dt><dd className="inline">{item['clause_identifier']}</dd></div>
                            )}
                            {typeof item['clause_category'] === 'string' && (
                              <div><dt className="inline font-medium">Source category: </dt><dd className="inline">{displayLabel(item['clause_category'])}</dd></div>
                            )}
                            {typeof item['verification_status'] === 'string' && (
                              <div className={item['verification_status'] === 'verified' ? 'text-emerald-dark' : 'text-graphite-700'}>
                                <dt className="inline font-medium">Clause status: </dt>
                                <dd className="inline">
                                  {item['verification_status'] === 'verified'
                                    ? 'Human verified'
                                    : `${displayLabel(item['verification_status'])} — not verified`}
                                </dd>
                              </div>
                            )}
                            {typeof item['extraction_method'] === 'string' && (
                              <div><dt className="inline font-medium">Extraction: </dt><dd className="inline">{item['extraction_method']}</dd></div>
                            )}
                          </dl>
                          {typeof item['text'] === 'string' && (
                            <p className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-ivory-200 pt-2 text-xs leading-5 text-graphite-700">
                              {item['text']}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function CustomerCommunicationsSection({
  claimId,
  claimantName,
  claimNumber,
}: {
  claimId: string
  claimantName: string | null
  claimNumber: string
}) {
  const queryClient = useQueryClient()
  const emailsQueryKey = ['claims', claimId, 'emails']
  const { data: emails, isLoading, error } = useQuery({
    queryKey: emailsQueryKey,
    queryFn: () => getClaimEmails(claimId),
  })

  const [showDraftForm, setShowDraftForm] = useState(false)
  const [eventType, setEventType] = useState('additional_evidence_required')
  const [recipientEmail, setRecipientEmail] = useState(
    claimNumber ? `${claimNumber.toLowerCase()}@policyholder.example.com` : ''
  )
  const [requestedDocs, setRequestedDocs] = useState('Detailed medical bills, discharge summary')
  const [actionError, setActionError] = useState<string | null>(null)

  const draftMutation = useMutation({
    mutationFn: () =>
      createCustomerEmailDraft(claimId, {
        event_type: eventType,
        recipient_email: recipientEmail,
        recipient_name: claimantName || 'Policyholder',
        requested_documents: requestedDocs.split(',').map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      setShowDraftForm(false)
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey: emailsQueryKey })
    },
    onError: (err) => setActionError(errorMessage(err, 'Failed to draft email.')),
  })

  const approveMutation = useMutation({
    mutationFn: (emailId: string) => approveCustomerEmail(claimId, emailId),
    onSuccess: () => {
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey: emailsQueryKey })
    },
    onError: (err) => setActionError(errorMessage(err, 'Failed to approve email.')),
  })

  const sendMutation = useMutation({
    mutationFn: (emailId: string) => sendCustomerEmail(claimId, emailId),
    onSuccess: () => {
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey: emailsQueryKey })
    },
    onError: (err) => setActionError(errorMessage(err, 'Failed to send email.')),
  })

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Mail className="size-4 text-emerald" />
            <CardTitle>Customer communications</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-emerald/40 text-emerald-dark">
              Human approval gate
            </Badge>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowDraftForm(!showDraftForm)}
            >
              {showDraftForm ? 'Cancel draft' : 'Draft email'}
            </Button>
          </div>
        </div>
        <p className="text-xs text-graphite-600">
          Strict policy: All external customer communications require explicit human authorization before dispatch.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {actionError && (
          <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700" role="alert">
            {actionError}
          </div>
        )}

        {showDraftForm && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              draftMutation.mutate()
            }}
            className="rounded-xl border border-ivory-300 bg-champagne-light/40 p-4 space-y-3"
          >
            <h4 className="text-xs font-semibold text-graphite-900">Prepare email draft</h4>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label className="text-xs">Communication event</Label>
                <select
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value)}
                  className="mt-1 w-full rounded-md border border-ivory-300 bg-white px-3 py-1.5 text-xs text-graphite-900"
                >
                  <option value="additional_evidence_required">Request additional documents</option>
                  <option value="claim_received">Claim received acknowledgment</option>
                  <option value="investigation_completed">Investigation completed update</option>
                  <option value="human_review_required">Specialist review notice</option>
                  <option value="review_completed">Review completed notice</option>
                </select>
              </div>
              <div>
                <Label className="text-xs">Recipient email</Label>
                <Input
                  className="mt-1 text-xs"
                  type="email"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  required
                />
              </div>
            </div>

            {eventType === 'additional_evidence_required' && (
              <div>
                <Label className="text-xs">Requested documents (comma separated)</Label>
                <Input
                  className="mt-1 text-xs"
                  value={requestedDocs}
                  onChange={(e) => setRequestedDocs(e.target.value)}
                  placeholder="e.g. Itemized hospital bill, pharmacy receipts"
                />
                <p className="mt-1 text-[11px] text-graphite-500">
                  A secure, encrypted upload token and link will be automatically generated.
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowDraftForm(false)}
              >
                Cancel
              </Button>
              <Button type="submit" size="sm" disabled={draftMutation.isPending}>
                {draftMutation.isPending && (
                  <LoaderCircle className="size-3 animate-spin mr-1" />
                )}
                Save draft for review
              </Button>
            </div>
          </form>
        )}

        {isLoading ? (
          <p className="text-xs text-graphite-500">Loading communications…</p>
        ) : error ? (
          <p className="text-xs text-red-600">Failed to load email history.</p>
        ) : !emails || emails.length === 0 ? (
          <p className="text-xs text-graphite-500">No customer communications yet.</p>
        ) : (
          <div className="space-y-3">
            {emails.map((email) => (
              <div
                key={email.id}
                className="rounded-xl border border-ivory-200 bg-white p-3 space-y-2 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-graphite-900">
                      {email.subject}
                    </span>
                    <Badge
                      variant={
                        email.status === 'sent' || email.status === 'replied'
                          ? 'outline'
                          : email.status === 'approved'
                          ? 'secondary'
                          : email.status === 'drafted'
                          ? 'accent'
                          : 'outline'
                      }
                      className="capitalize"
                    >
                      {email.status}
                    </Badge>
                  </div>
                  <span className="text-graphite-500 text-[11px]">
                    {new Date(email.created_at).toLocaleDateString()}
                  </span>
                </div>

                <div className="text-graphite-600 text-[11px]">
                  <span>To: <strong>{email.recipient_name}</strong> ({email.recipient_email})</span>
                  {email.approved_by_name && (
                    <span className="ml-3 text-emerald-dark">
                      ✓ Approved by {email.approved_by_name}
                    </span>
                  )}
                  {email.follow_up_deadline && (
                    <span className="ml-3 text-amber-700">
                      Deadline: {new Date(email.follow_up_deadline).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {email.secure_upload_url && (
                  <div className="rounded bg-ivory-50 p-2 text-[11px] font-mono break-all text-graphite-700">
                    Upload Link: {email.secure_upload_url}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {email.status === 'drafted' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      className="h-7 text-xs"
                      disabled={approveMutation.isPending}
                      onClick={() => approveMutation.mutate(email.id)}
                    >
                      Approve communication
                    </Button>
                  )}
                  {email.status === 'approved' && (
                    <Button
                      size="sm"
                      variant="default"
                      className="h-7 text-xs"
                      disabled={sendMutation.isPending}
                      onClick={() => sendMutation.mutate(email.id)}
                    >
                      <Send className="size-3 mr-1" />
                      Send to customer
                    </Button>
                  )}
                  {email.status === 'sent' && (
                    <span className="text-[11px] text-emerald-dark font-medium flex items-center gap-1">
                      <CheckCircle2 className="size-3" />
                      Sent {email.sent_at ? new Date(email.sent_at).toLocaleTimeString() : ''}
                    </span>
                  )}
                  {email.status === 'replied' && (
                    <span className="text-[11px] text-blue-700 font-medium flex items-center gap-1">
                      <CheckCircle2 className="size-3" />
                      Customer responded with requested documentation
                    </span>
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

function ClaimAuditTimelineSection({ claimId }: { claimId: string }) {
  const [page, setPage] = useState(0)
  const [category, setCategory] = useState<string>('')
  const [actorType, setActorType] = useState<string>('')
  const [outcome, setOutcome] = useState<string>('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const pageSize = 10

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['claim-audit-timeline', claimId, page, category, actorType, outcome],
    queryFn: () =>
      getClaimAuditTimeline(claimId, {
        limit: pageSize,
        offset: page * pageSize,
        ...(category ? { event_category: category } : {}),
        ...(actorType ? { actor_type: actorType } : {}),
        ...(outcome ? { outcome } : {}),
      }),
  })

  const totalPages = data ? Math.ceil(data.total_count / pageSize) : 0

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
              <CardTitle>Enterprise Audit Trail</CardTitle>
              {data && (
                <Badge variant="outline" className="text-xs">
                  {data.total_count} events
                </Badge>
              )}
            </div>
            <p className="text-xs text-graphite-600">
              Centralized, append-only traceability of employee actions, AI agents, and system workflows.
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
        {/* Filter Toolbar */}
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-ivory-100 p-2 text-xs">
          <span className="text-graphite-600 font-medium">Filter:</span>
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value)
              setPage(0)
            }}
            className="rounded border border-ivory-300 bg-white px-2 py-1 text-xs text-graphite-800"
          >
            <option value="">All Categories</option>
            <option value="claim">Claim</option>
            <option value="evidence">Evidence</option>
            <option value="investigation">Investigation</option>
            <option value="agent_execution">Agent Execution</option>
            <option value="finding">Finding</option>
            <option value="human_review">Human Review</option>
            <option value="customer_email">Customer Email</option>
            <option value="auth">Auth</option>
            <option value="policy">Policy</option>
          </select>
          <select
            value={actorType}
            onChange={(e) => {
              setActorType(e.target.value)
              setPage(0)
            }}
            className="rounded border border-ivory-300 bg-white px-2 py-1 text-xs text-graphite-800"
          >
            <option value="">All Actor Types</option>
            <option value="employee">Employee</option>
            <option value="ai_agent">AI Agent</option>
            <option value="system">System</option>
          </select>
          <select
            value={outcome}
            onChange={(e) => {
              setOutcome(e.target.value)
              setPage(0)
            }}
            className="rounded border border-ivory-300 bg-white px-2 py-1 text-xs text-graphite-800"
          >
            <option value="">All Outcomes</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
            <option value="denied">Denied</option>
            <option value="error">Error</option>
          </select>
          {(category || actorType || outcome) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setCategory('')
                setActorType('')
                setOutcome('')
                setPage(0)
              }}
              className="h-6 px-2 text-xs text-graphite-600"
            >
              Reset filters
            </Button>
          )}
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-xs text-graphite-500">
            <LoaderCircle className="size-4 animate-spin mr-2" />
            Loading audit events…
          </div>
        ) : error ? (
          <div className="rounded-lg bg-rose-50 p-4 text-xs text-rose-700">
            Failed to load audit history.
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="py-6 text-center text-xs text-graphite-500">
            No audit events found matching the specified criteria.
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

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-ivory-200 pt-3 text-xs text-graphite-600">
                <div>
                  Showing {page * pageSize + 1} to{' '}
                  {Math.min((page + 1) * pageSize, data.total_count)} of{' '}
                  {data.total_count} events
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    className="h-7 px-2 text-xs"
                  >
                    <ChevronLeft className="size-3.5 mr-0.5" />
                    Previous
                  </Button>
                  <span className="px-2 font-medium">
                    {page + 1} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page + 1 >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="h-7 px-2 text-xs"
                  >
                    Next
                    <ChevronRight className="size-3.5 ml-0.5" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function ClaimDetailPage() {
  const { claimId = '' } = useParams()
  const { data: claim, error, isError, isFetching, isPending, refetch } =
    useClaimDetail(claimId)

  return (
    <PageContainer
      actions={
        <Button asChild variant="outline">
          <Link to="/claims">
            <ArrowLeft aria-hidden="true" />
            Back to claims
          </Link>
        </Button>
      }
      breadcrumbs={[
        { label: 'Workspace', href: '/' },
        { label: 'Claims', href: '/claims' },
        { label: claim?.claim_number ?? 'Claim detail' },
      ]}
      description="Review claim information, provide supporting documents, and request an evidence-grounded investigation."
      eyebrow="Claims workspace"
      title={claim?.claim_number ?? 'Claim detail'}
    >
      <div className="space-y-4">
        <HumanReviewNotice />
        {isPending ? (
          <ClaimLoading />
        ) : isError ? (
          <ClaimLoadError
            error={error}
            isRetrying={isFetching}
            onRetry={() => void refetch()}
          />
        ) : claim ? (
          <>
            <ClaimOverview claim={claim} />
            <div className="grid items-start gap-4 xl:grid-cols-2">
              <UploadSection claimId={claimId} />
              <InvestigationSection
                claimId={claimId}
                claimType={claim.claim_type}
              />
            </div>
            <CustomerCommunicationsSection
              claimId={claimId}
              claimantName={claim.claimant_name}
              claimNumber={claim.claim_number}
            />
            <ClaimAuditTimelineSection claimId={claimId} />
            <ClaimInvestigationHistory claimId={claimId} />
          </>
        ) : null}
      </div>
    </PageContainer>
  )
}
