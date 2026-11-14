import { useState, type FormEvent } from 'react'
import { isAxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  FileCheck2,
  FileText,
  History,
  Link2,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Shield,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageContainer } from '@/components/layout/page-container'
import { useAuth } from '@/features/auth/auth-context'
import {
  addPolicyCoverage,
  addPolicyExclusion,
  getPolicyClaims,
  getPolicyClauses,
  getPolicyDetail,
  linkPolicyToClaim,
  removePolicyCoverage,
  removePolicyExclusion,
  retryPolicyEmbedding,
  updatePolicy,
  verifyPolicyClause,
} from '@/features/policies/policy-api'
import type {
  ExclusionType,
  PolicyCoverageCreateRequest,
  PolicyExclusionCreateRequest,
  PolicyUpdateRequest,
} from '@/types/policies'

function formatMoney(amount: string | number | null) {
  if (amount === null || amount === undefined) return 'Unlimited'
  const num = Number(amount)
  if (Number.isNaN(num)) return String(amount)
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(num)
}

function formatDate(val: string | null) {
  if (!val) return 'Continuous'
  const d = new Date(val)
  return Number.isNaN(d.getTime()) ? val : d.toLocaleDateString()
}

export function PolicyDetailPage() {
  const { employee } = useAuth()
  const isAdmin = employee?.role?.toLowerCase() === 'admin'
  const { policyId = '' } = useParams()
  const queryClient = useQueryClient()

  // Tab State
  const [activeTab, setActiveTab] = useState<
    'coverages' | 'exclusions' | 'clauses' | 'claims'
  >('coverages')

  // Modals and Forms
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isAddCoverageOpen, setIsAddCoverageOpen] = useState(false)
  const [isAddExclusionOpen, setIsAddExclusionOpen] = useState(false)
  const [isLinkClaimOpen, setIsLinkClaimOpen] = useState(false)

  // Edit Policy Form State
  const [editInsurer, setEditInsurer] = useState('')
  const [editProduct, setEditProduct] = useState('')
  const [editVersion, setEditVersion] = useState('')
  const [editFrom, setEditFrom] = useState('')
  const [editTo, setEditTo] = useState('')
  const [editSourceUrl, setEditSourceUrl] = useState('')
  const [editError, setEditError] = useState<string | null>(null)

  // Add Coverage Form State
  const [covName, setCovName] = useState('')
  const [covCategory, setCovCategory] = useState('inpatient')
  const [covLimit, setCovLimit] = useState('')
  const [covDeductible, setCovDeductible] = useState('')
  const [covCopay, setCovCopay] = useState('')
  const [covWaitingDays, setCovWaitingDays] = useState('')
  const [covDesc, setCovDesc] = useState('')
  const [covOptional, setCovOptional] = useState(false)
  const [covError, setCovError] = useState<string | null>(null)

  // Add Exclusion Form State
  const [exclCode, setExclCode] = useState('')
  const [exclTitle, setExclTitle] = useState('')
  const [exclDesc, setExclDesc] = useState('')
  const [exclMonths, setExclMonths] = useState('')
  const [exclType, setExclType] = useState<ExclusionType>('permanent')
  const [exclError, setExclError] = useState<string | null>(null)

  // Link Claim Form State
  const [targetClaimId, setTargetClaimId] = useState('')
  const [linkClaimError, setLinkClaimError] = useState<string | null>(null)
  const [linkSuccess, setLinkSuccess] = useState<string | null>(null)

  // Feedback notifications
  const [feedback, setFeedback] = useState<string | null>(null)

  // Fetch Policy Detail
  const {
    data: policy,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['policy-detail', policyId],
    queryFn: () => getPolicyDetail(policyId),
    enabled: Boolean(policyId),
  })

  // Fetch Linked Claims
  const { data: linkedClaims } = useQuery({
    queryKey: ['policy-claims', policyId],
    queryFn: () => getPolicyClaims(policyId),
    enabled: Boolean(policyId) && activeTab === 'claims',
  })

  // Fetch Policy Clauses
  const { data: clauses } = useQuery({
    queryKey: ['policy-clauses', policyId],
    queryFn: () => getPolicyClauses(policyId),
    enabled: Boolean(policyId) && activeTab === 'clauses',
  })

  // Mutations
  const updateMutation = useMutation({
    mutationFn: (payload: PolicyUpdateRequest) => updatePolicy(policyId, payload),
    onSuccess: () => {
      setIsEditOpen(false)
      setFeedback('Policy metadata updated successfully.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setEditError(err.response?.data?.detail ?? 'Failed to update policy.')
      } else {
        setEditError('Unexpected error updating policy.')
      }
    },
  })

  const addCoverageMutation = useMutation({
    mutationFn: (payload: PolicyCoverageCreateRequest) =>
      addPolicyCoverage(policyId, payload),
    onSuccess: () => {
      setIsAddCoverageOpen(false)
      resetCoverageForm()
      setFeedback('Coverage term added successfully.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setCovError(err.response?.data?.detail ?? 'Failed to add coverage.')
      } else {
        setCovError('Unexpected error adding coverage.')
      }
    },
  })

  const removeCoverageMutation = useMutation({
    mutationFn: (coverageId: string) => removePolicyCoverage(policyId, coverageId),
    onSuccess: () => {
      setFeedback('Coverage removed successfully.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
  })

  const addExclusionMutation = useMutation({
    mutationFn: (payload: PolicyExclusionCreateRequest) =>
      addPolicyExclusion(policyId, payload),
    onSuccess: () => {
      setIsAddExclusionOpen(false)
      resetExclusionForm()
      setFeedback('Exclusion added successfully.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setExclError(err.response?.data?.detail ?? 'Failed to add exclusion.')
      } else {
        setExclError('Unexpected error adding exclusion.')
      }
    },
  })

  const removeExclusionMutation = useMutation({
    mutationFn: (exclusionId: string) => removePolicyExclusion(policyId, exclusionId),
    onSuccess: () => {
      setFeedback('Exclusion removed successfully.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
  })

  const linkClaimMutation = useMutation({
    mutationFn: (claimId: string) => linkPolicyToClaim(policyId, claimId),
    onSuccess: (data) => {
      setLinkSuccess(`Successfully bound claim ${data.claim_number} to this policy.`)
      setTargetClaimId('')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
      void queryClient.invalidateQueries({ queryKey: ['policy-claims', policyId] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setLinkClaimError(err.response?.data?.detail ?? 'Failed to link claim.')
      } else {
        setLinkClaimError('Unexpected error linking claim.')
      }
    },
  })

  const verifyClauseMutation = useMutation({
    mutationFn: ({
      clauseId,
      status,
    }: {
      clauseId: string
      status: 'verified' | 'needs_review'
    }) => verifyPolicyClause(policyId, clauseId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['policy-clauses', policyId] })
    },
  })

  const retryEmbeddingMutation = useMutation({
    mutationFn: () => retryPolicyEmbedding(policyId),
    onSuccess: () => {
      setFeedback('Embedding process initiated.')
      void queryClient.invalidateQueries({ queryKey: ['policy-detail', policyId] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setFeedback(err.response?.data?.detail ?? 'Embedding generation failed.')
      }
    },
  })

  const resetCoverageForm = () => {
    setCovName('')
    setCovCategory('inpatient')
    setCovLimit('')
    setCovDeductible('')
    setCovCopay('')
    setCovWaitingDays('')
    setCovDesc('')
    setCovOptional(false)
    setCovError(null)
  }

  const resetExclusionForm = () => {
    setExclCode('')
    setExclTitle('')
    setExclDesc('')
    setExclMonths('')
    setExclType('permanent')
    setExclError(null)
  }

  const handleOpenEdit = () => {
    if (!policy) return
    setEditInsurer(policy.insurer_name ?? '')
    setEditProduct(policy.product_name ?? '')
    setEditVersion(policy.policy_version ?? 'v1.0')
    setEditFrom(policy.effective_from ?? '')
    setEditTo(policy.effective_to ?? '')
    setEditSourceUrl(policy.source_url ?? '')
    setEditError(null)
    setIsEditOpen(true)
  }

  const handleEditSubmit = (e: FormEvent) => {
    e.preventDefault()
    setEditError(null)
    updateMutation.mutate({
      insurer_name: editInsurer.trim() || null,
      product_name: editProduct.trim() || null,
      policy_version: editVersion.trim() || null,
      effective_from: editFrom || null,
      effective_to: editTo || null,
      source_url: editSourceUrl.trim() || null,
    })
  }

  const handleAddCoverageSubmit = (e: FormEvent) => {
    e.preventDefault()
    setCovError(null)
    if (!covName.trim()) {
      setCovError('Coverage name is required.')
      return
    }
    addCoverageMutation.mutate({
      coverage_name: covName.trim(),
      coverage_category: covCategory,
      benefit_limit: covLimit ? Number(covLimit) : null,
      deductible: covDeductible ? Number(covDeductible) : null,
      co_pay_percentage: covCopay ? Number(covCopay) : null,
      waiting_period_days: covWaitingDays ? Number(covWaitingDays) : null,
      description: covDesc.trim() || null,
      is_optional: covOptional,
    })
  }

  const handleAddExclusionSubmit = (e: FormEvent) => {
    e.preventDefault()
    setExclError(null)
    if (!exclTitle.trim() || !exclDesc.trim()) {
      setExclError('Title and description are required.')
      return
    }
    addExclusionMutation.mutate({
      exclusion_code: exclCode.trim() || null,
      title: exclTitle.trim(),
      description: exclDesc.trim(),
      waiting_period_months: exclMonths ? Number(exclMonths) : null,
      exclusion_type: exclType,
    })
  }

  const handleLinkClaimSubmit = (e: FormEvent) => {
    e.preventDefault()
    setLinkClaimError(null)
    setLinkSuccess(null)
    if (!targetClaimId.trim()) {
      setLinkClaimError('Please provide a valid claim UUID.')
      return
    }
    linkClaimMutation.mutate(targetClaimId.trim())
  }

  if (isLoading) {
    return (
      <PageContainer title="Loading Policy…">
        <div className="flex items-center justify-center py-20 text-xs text-graphite-500">
          <LoaderCircle className="size-5 animate-spin mr-2" />
          Loading policy information…
        </div>
      </PageContainer>
    )
  }

  if (error || !policy) {
    return (
      <PageContainer title="Policy Not Found">
        <Card className="p-8 text-center text-xs text-rose-700 bg-rose-50 border-rose-200">
          <AlertCircle className="size-6 mx-auto mb-2 text-rose-600" />
          <h3 className="font-bold text-sm">Policy Not Found or Access Denied</h3>
          <p className="mt-1 text-graphite-600">
            You may not have authorization to view this policy document.
          </p>
          <Button asChild variant="outline" size="sm" className="mt-4 text-xs">
            <Link to="/policies">Back to policies</Link>
          </Button>
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer
      actions={
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/policies">
              <ArrowLeft className="size-3.5 mr-1" />
              Back
            </Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`size-3.5 mr-1 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {isAdmin && (
            <Button size="sm" onClick={handleOpenEdit}>
              <Pencil className="size-3.5 mr-1" />
              Edit Policy
            </Button>
          )}
        </div>
      }
      breadcrumbs={[
        { label: 'Workspace', href: '/' },
        { label: 'Policies', href: '/policies' },
        { label: policy.policy_identifier },
      ]}
      description="Manage coverage limits, deductibles, waiting periods, clauses, and claims linked to this policy version."
      eyebrow={policy.insurance_type?.toUpperCase() ?? 'HEALTH'}
      title={policy.policy_identifier}
    >
      <div className="space-y-4">
        {feedback && (
          <div className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-800 flex items-center justify-between">
            <span>{feedback}</span>
            <button
              type="button"
              onClick={() => setFeedback(null)}
              className="text-emerald-700 hover:text-emerald-900"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        {/* Overview Header Card */}
        <Card>
          <CardContent className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-bold text-graphite-900">
                    {policy.product_name || 'Standard Coverage Plan'}
                  </h3>
                  <Badge variant="secondary" className="font-mono text-xs">
                    {policy.policy_version ?? 'v1.0'}
                  </Badge>
                  {policy.has_document_attached ? (
                    <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-emerald-700 text-xs">
                      <FileCheck2 className="size-3 mr-1" />
                      PDF Attached
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-gray-600 text-xs">
                      Document Pending
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-graphite-600 font-medium">
                  {policy.insurer_name}
                </p>
                {policy.source_url && (
                  <a
                    href={policy.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] text-emerald-700 hover:underline"
                  >
                    <span>View Official Source</span>
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </div>

              <div className="rounded-xl border border-ivory-200 bg-ivory-50 p-3 text-xs space-y-1 text-graphite-700 min-w-[220px]">
                <div className="flex justify-between">
                  <span className="text-graphite-500">Effective:</span>
                  <span className="font-semibold">{formatDate(policy.effective_from)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-graphite-500">Expires:</span>
                  <span className="font-semibold">{formatDate(policy.effective_to)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-graphite-500">Linked Claims:</span>
                  <span className="font-bold text-graphite-900">{policy.linked_claims_count}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 border-b border-ivory-200 pb-2 text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('coverages')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors ${
              activeTab === 'coverages'
                ? 'bg-graphite-900 text-white'
                : 'text-graphite-600 hover:bg-ivory-100'
            }`}
          >
            <Shield className="size-3.5" />
            <span>Coverages & Limits</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">
              {policy.coverages?.length ?? 0}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('exclusions')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors ${
              activeTab === 'exclusions'
                ? 'bg-graphite-900 text-white'
                : 'text-graphite-600 hover:bg-ivory-100'
            }`}
          >
            <ShieldAlert className="size-3.5" />
            <span>Exclusions</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">
              {policy.exclusions?.length ?? 0}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('clauses')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors ${
              activeTab === 'clauses'
                ? 'bg-graphite-900 text-white'
                : 'text-graphite-600 hover:bg-ivory-100'
            }`}
          >
            <FileText className="size-3.5" />
            <span>Document & Clauses</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">
              {policy.clause_count}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('claims')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors ${
              activeTab === 'claims'
                ? 'bg-graphite-900 text-white'
                : 'text-graphite-600 hover:bg-ivory-100'
            }`}
          >
            <Link2 className="size-3.5" />
            <span>Linked Claims</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">
              {policy.linked_claims_count}
            </span>
          </button>
        </div>

        {/* Tab 1: Coverages */}
        {activeTab === 'coverages' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="font-bold text-graphite-900 text-sm">Coverages and Benefit Limits</h4>
                <p className="text-xs text-graphite-500">
                  Specified treatments, room rent, and procedure limits for this policy.
                </p>
              </div>
              {isAdmin && (
                <Button size="sm" onClick={() => setIsAddCoverageOpen(true)}>
                  <Plus className="size-3.5 mr-1" />
                  Add Coverage Term
                </Button>
              )}
            </div>

            {!policy.coverages || policy.coverages.length === 0 ? (
              <Card className="p-8 text-center text-xs text-graphite-500">
                No coverage terms defined yet. Click "Add Coverage Term" to define benefit limits.
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {policy.coverages.map((cov) => (
                  <Card key={cov.id} className="p-4 space-y-2 text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-graphite-900 text-sm">
                            {cov.coverage_name}
                          </span>
                          {cov.is_optional && (
                            <Badge variant="outline" className="text-[10px]">
                              Add-on
                            </Badge>
                          )}
                        </div>
                        <span className="rounded bg-ivory-200 px-1.5 py-0.5 text-[10px] font-mono text-graphite-600 uppercase">
                          {cov.coverage_category}
                        </span>
                      </div>
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => removeCoverageMutation.mutate(cov.id)}
                          disabled={removeCoverageMutation.isPending}
                          className="text-graphite-400 hover:text-rose-600 p-1"
                          title="Remove coverage"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-2 rounded bg-ivory-50 p-2 text-[11px] text-graphite-700">
                      <div>
                        <span className="text-graphite-500 block">Limit:</span>
                        <span className="font-semibold">{formatMoney(cov.benefit_limit)}</span>
                      </div>
                      <div>
                        <span className="text-graphite-500 block">Deductible:</span>
                        <span className="font-semibold">{formatMoney(cov.deductible)}</span>
                      </div>
                      <div>
                        <span className="text-graphite-500 block">Co-Pay:</span>
                        <span className="font-semibold">
                          {cov.co_pay_percentage ? `${cov.co_pay_percentage}%` : 'Nil'}
                        </span>
                      </div>
                      <div>
                        <span className="text-graphite-500 block">Waiting Period:</span>
                        <span className="font-semibold">
                          {cov.waiting_period_days ? `${cov.waiting_period_days} days` : 'Immediate'}
                        </span>
                      </div>
                    </div>

                    {cov.description && (
                      <p className="text-[11px] text-graphite-600">{cov.description}</p>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Exclusions */}
        {activeTab === 'exclusions' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="font-bold text-graphite-900 text-sm">Explicit Policy Exclusions</h4>
                <p className="text-xs text-graphite-500">
                  Conditions, treatments, or perils not covered or subject to waiting periods.
                </p>
              </div>
              {isAdmin && (
                <Button size="sm" onClick={() => setIsAddExclusionOpen(true)}>
                  <Plus className="size-3.5 mr-1" />
                  Add Exclusion
                </Button>
              )}
            </div>

            {!policy.exclusions || policy.exclusions.length === 0 ? (
              <Card className="p-8 text-center text-xs text-graphite-500">
                No explicit exclusions recorded. Click "Add Exclusion" to define policy exclusions.
              </Card>
            ) : (
              <div className="space-y-3">
                {policy.exclusions.map((excl) => (
                  <Card key={excl.id} className="p-4 space-y-2 text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {excl.exclusion_code && (
                          <span className="font-mono text-[10px] bg-rose-50 border border-rose-200 text-rose-700 px-1.5 py-0.5 rounded">
                            {excl.exclusion_code}
                          </span>
                        )}
                        <span className="font-bold text-graphite-900 text-sm">
                          {excl.title}
                        </span>
                        <Badge variant="outline" className="capitalize text-[10px]">
                          {excl.exclusion_type.replace('_', ' ')}
                        </Badge>
                        {excl.waiting_period_months && (
                          <span className="text-[11px] text-amber-700 font-medium">
                            ({excl.waiting_period_months} months waiting)
                          </span>
                        )}
                      </div>
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => removeExclusionMutation.mutate(excl.id)}
                          disabled={removeExclusionMutation.isPending}
                          className="text-graphite-400 hover:text-rose-600 p-1"
                          title="Remove exclusion"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      )}
                    </div>
                    <p className="text-graphite-700 text-xs leading-relaxed">{excl.description}</p>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Documents & Clauses */}
        {activeTab === 'clauses' && (
          <div className="space-y-4">
            <Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h4 className="font-bold text-graphite-900 text-xs">Source Document Attachment</h4>
                  <p className="text-[11px] text-graphite-500">
                    {policy.has_document_attached
                      ? `PDF File: ${policy.filename} (${(policy.file_size_bytes / 1024).toFixed(1)} KB)`
                      : 'No PDF document has been attached to this policy yet.'}
                  </p>
                </div>
                {policy.has_document_attached && isAdmin && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => retryEmbeddingMutation.mutate()}
                    disabled={retryEmbeddingMutation.isPending}
                    className="text-xs"
                  >
                    <RefreshCw className="size-3 mr-1" />
                    Re-index Embeddings
                  </Button>
                )}
              </div>
            </Card>

            <div className="space-y-2">
              <h4 className="font-bold text-graphite-900 text-xs">Extracted Policy Clauses</h4>
              {!clauses || clauses.length === 0 ? (
                <Card className="p-6 text-center text-xs text-graphite-500">
                  {policy.has_document_attached
                    ? 'No clauses extracted or clause extraction is processing.'
                    : 'Attach a PDF policy document to automatically extract and index source clauses.'}
                </Card>
              ) : (
                <div className="space-y-2">
                  {clauses.map((clause) => (
                    <Card key={clause.id} className="p-3 text-xs space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-semibold text-graphite-900">
                            {clause.clause_identifier}
                          </span>
                          <span className="rounded bg-ivory-200 px-1.5 py-0.5 text-[10px] font-mono text-graphite-700">
                            Page {clause.source_page_number}
                          </span>
                          <Badge variant="outline" className="capitalize text-[10px]">
                            {clause.clause_category}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2">
                          {clause.verification_status === 'verified' ? (
                            <span className="text-emerald-700 font-medium text-[11px] flex items-center gap-1">
                              <CheckCircle2 className="size-3" />
                              Verified
                            </span>
                          ) : isAdmin ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                verifyClauseMutation.mutate({
                                  clauseId: clause.id,
                                  status: 'verified',
                                })
                              }
                              className="h-6 text-[10px] px-2 text-emerald-700 border-emerald-300 hover:bg-emerald-50"
                            >
                              Verify Clause
                            </Button>
                          ) : (
                            <Badge variant="outline" className="text-[10px] capitalize">
                              {clause.verification_status.replace('_', ' ')}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <p className="text-graphite-700 leading-relaxed text-[11px] whitespace-pre-wrap bg-ivory-50 p-2 rounded">
                        {clause.clause_text}
                      </p>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 4: Linked Claims */}
        {activeTab === 'claims' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="font-bold text-graphite-900 text-sm">Linked Insurance Claims</h4>
                <p className="text-xs text-graphite-500">
                  Claims actively bound to this policy version for coverage verification.
                </p>
              </div>
              {isAdmin && (
                <Button size="sm" onClick={() => setIsLinkClaimOpen(true)}>
                  <Link2 className="size-3.5 mr-1" />
                  Bind Claim
                </Button>
              )}
            </div>

            {!linkedClaims || linkedClaims.length === 0 ? (
              <Card className="p-8 text-center text-xs text-graphite-500">
                No claims are currently bound to this policy version.
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {linkedClaims.map((claim) => (
                  <Card key={claim.id} className="p-4 space-y-2 text-xs">
                    <div className="flex items-center justify-between">
                      <Link
                        to={`/claims/${claim.id}`}
                        className="font-bold text-graphite-900 text-sm hover:text-emerald-dark hover:underline flex items-center gap-1"
                      >
                        {claim.claim_number}
                        <ExternalLink className="size-3" />
                      </Link>
                      <Badge variant="outline" className="capitalize text-[10px]">
                        {claim.status}
                      </Badge>
                    </div>
                    <div className="space-y-1 text-[11px] text-graphite-600">
                      <div>Claimant: <span className="font-semibold text-graphite-800">{claim.claimant_name}</span></div>
                      <div>Type: <span className="capitalize">{claim.claim_type}</span></div>
                      <div>Loss Date: {claim.loss_date ? formatDate(claim.loss_date) : 'Not recorded'}</div>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Audit History Notice */}
        <Card className="bg-ivory-50 border-ivory-200 p-4">
          <div className="flex items-start gap-3">
            <History className="size-5 text-graphite-500 shrink-0 mt-0.5" />
            <div className="text-xs text-graphite-600 space-y-1">
              <p className="font-semibold text-graphite-900">
                Centralized Enterprise Audit Trail
              </p>
              <p>
                All policy creation, updates, coverage changes, exclusion removals, and claim link operations
                are immutably logged into the centralized audit service. When investigating an authorized claim,
                policy verification and grounding events appear directly in the claim's audit timeline.
              </p>
            </div>
          </div>
        </Card>

        {/* Modal: Edit Policy */}
        {isEditOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-ivory-200 pb-3">
                <h3 className="font-bold text-graphite-900 text-sm">Edit Policy Metadata</h3>
                <button type="button" onClick={() => setIsEditOpen(false)}>
                  <X className="size-4 text-graphite-400" />
                </button>
              </div>

              {editError && (
                <div className="rounded-lg bg-rose-50 p-2.5 text-rose-700">
                  {editError}
                </div>
              )}

              <form onSubmit={handleEditSubmit} className="space-y-3">
                <div>
                  <Label className="text-xs">Insurer Name</Label>
                  <Input
                    value={editInsurer}
                    onChange={(e) => setEditInsurer(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>
                <div>
                  <Label className="text-xs">Product Name</Label>
                  <Input
                    value={editProduct}
                    onChange={(e) => setEditProduct(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>
                <div>
                  <Label className="text-xs">Version</Label>
                  <Input
                    value={editVersion}
                    onChange={(e) => setEditVersion(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Effective From</Label>
                    <Input
                      type="date"
                      value={editFrom}
                      onChange={(e) => setEditFrom(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Effective To</Label>
                    <Input
                      type="date"
                      value={editTo}
                      onChange={(e) => setEditTo(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                </div>
                <div>
                  <Label className="text-xs">Source URL</Label>
                  <Input
                    type="url"
                    value={editSourceUrl}
                    onChange={(e) => setEditSourceUrl(e.target.value)}
                    className="mt-1 text-xs"
                  />
                </div>
                <div className="flex justify-end gap-2 pt-2 border-t border-ivory-200">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsEditOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" size="sm" disabled={updateMutation.isPending}>
                    Save Changes
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Add Coverage */}
        {isAddCoverageOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-ivory-200 pb-3">
                <h3 className="font-bold text-graphite-900 text-sm">Add Coverage Term</h3>
                <button type="button" onClick={() => setIsAddCoverageOpen(false)}>
                  <X className="size-4 text-graphite-400" />
                </button>
              </div>

              {covError && (
                <div className="rounded-lg bg-rose-50 p-2.5 text-rose-700">
                  {covError}
                </div>
              )}

              <form onSubmit={handleAddCoverageSubmit} className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Coverage Name *</Label>
                    <Input
                      placeholder="e.g. Day Care Surgery"
                      value={covName}
                      onChange={(e) => setCovName(e.target.value)}
                      className="mt-1 text-xs"
                      required
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Category</Label>
                    <select
                      value={covCategory}
                      onChange={(e) => setCovCategory(e.target.value)}
                      className="mt-1 w-full rounded-md border border-ivory-300 bg-white px-2 py-1.5 text-xs text-graphite-900"
                    >
                      <option value="inpatient">Inpatient</option>
                      <option value="outpatient">Outpatient</option>
                      <option value="daycare">Day Care</option>
                      <option value="critical_illness">Critical Illness</option>
                      <option value="add_on">Add-on</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label className="text-xs">Benefit Limit (₹)</Label>
                    <Input
                      type="number"
                      min="0"
                      step="1000"
                      placeholder="Unlimited"
                      value={covLimit}
                      onChange={(e) => setCovLimit(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Deductible (₹)</Label>
                    <Input
                      type="number"
                      min="0"
                      step="1000"
                      placeholder="Nil"
                      value={covDeductible}
                      onChange={(e) => setCovDeductible(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Co-Pay (%)</Label>
                    <Input
                      type="number"
                      min="0"
                      max="100"
                      placeholder="0"
                      value={covCopay}
                      onChange={(e) => setCovCopay(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                </div>

                <div>
                  <Label className="text-xs">Waiting Period (Days)</Label>
                  <Input
                    type="number"
                    min="0"
                    placeholder="0"
                    value={covWaitingDays}
                    onChange={(e) => setCovWaitingDays(e.target.value)}
                    className="mt-1 text-xs"
                  />
                </div>

                <div>
                  <Label className="text-xs">Description</Label>
                  <textarea
                    rows={2}
                    value={covDesc}
                    onChange={(e) => setCovDesc(e.target.value)}
                    className="mt-1 w-full rounded-md border border-ivory-300 p-2 text-xs"
                    placeholder="Optional details, room rent sub-limits, or rules..."
                  />
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="covOptional"
                    checked={covOptional}
                    onChange={(e) => setCovOptional(e.target.checked)}
                    className="rounded border-ivory-300"
                  />
                  <Label htmlFor="covOptional" className="text-xs cursor-pointer">
                    This is an optional add-on coverage
                  </Label>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-ivory-200">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsAddCoverageOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={addCoverageMutation.isPending}
                  >
                    Save Coverage
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Add Exclusion */}
        {isAddExclusionOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-ivory-200 pb-3">
                <h3 className="font-bold text-graphite-900 text-sm">Add Policy Exclusion</h3>
                <button type="button" onClick={() => setIsAddExclusionOpen(false)}>
                  <X className="size-4 text-graphite-400" />
                </button>
              </div>

              {exclError && (
                <div className="rounded-lg bg-rose-50 p-2.5 text-rose-700">
                  {exclError}
                </div>
              )}

              <form onSubmit={handleAddExclusionSubmit} className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Exclusion Code</Label>
                    <Input
                      placeholder="e.g. EXCL-DENTAL"
                      value={exclCode}
                      onChange={(e) => setExclCode(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Exclusion Type</Label>
                    <select
                      value={exclType}
                      onChange={(e) => setExclType(e.target.value as ExclusionType)}
                      className="mt-1 w-full rounded-md border border-ivory-300 bg-white px-2 py-1.5 text-xs text-graphite-900"
                    >
                      <option value="permanent">Permanent Exclusion</option>
                      <option value="waiting_period">Waiting Period</option>
                      <option value="condition_based">Condition Based</option>
                      <option value="specified_illness">Specified Illness</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                </div>

                <div>
                  <Label className="text-xs">Title *</Label>
                  <Input
                    placeholder="e.g. Cosmetic & Aesthetic Surgery"
                    value={exclTitle}
                    onChange={(e) => setExclTitle(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>

                <div>
                  <Label className="text-xs">Waiting Period (Months)</Label>
                  <Input
                    type="number"
                    min="0"
                    placeholder="e.g. 24"
                    value={exclMonths}
                    onChange={(e) => setExclMonths(e.target.value)}
                    className="mt-1 text-xs"
                  />
                </div>

                <div>
                  <Label className="text-xs">Description *</Label>
                  <textarea
                    rows={3}
                    value={exclDesc}
                    onChange={(e) => setExclDesc(e.target.value)}
                    className="mt-1 w-full rounded-md border border-ivory-300 p-2 text-xs"
                    placeholder="Full exclusion definition or clause text..."
                    required
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-ivory-200">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsAddExclusionOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={addExclusionMutation.isPending}
                  >
                    Save Exclusion
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Bind Claim */}
        {isLinkClaimOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-ivory-200 pb-3">
                <h3 className="font-bold text-graphite-900 text-sm">Bind Claim to Policy</h3>
                <button type="button" onClick={() => setIsLinkClaimOpen(false)}>
                  <X className="size-4 text-graphite-400" />
                </button>
              </div>

              {linkClaimError && (
                <div className="rounded-lg bg-rose-50 p-2.5 text-rose-700">
                  {linkClaimError}
                </div>
              )}
              {linkSuccess && (
                <div className="rounded-lg bg-emerald-50 p-2.5 text-emerald-800">
                  {linkSuccess}
                </div>
              )}

              <form onSubmit={handleLinkClaimSubmit} className="space-y-3">
                <p className="text-graphite-600">
                  Associate an existing claim with this policy version. The system will validate that the claim loss date
                  falls within the policy active dates ({formatDate(policy.effective_from)} – {formatDate(policy.effective_to)}).
                </p>

                <div>
                  <Label className="text-xs">Claim UUID *</Label>
                  <Input
                    placeholder="Enter claim UUID..."
                    value={targetClaimId}
                    onChange={(e) => setTargetClaimId(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-ivory-200">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setIsLinkClaimOpen(false)
                      setLinkClaimError(null)
                      setLinkSuccess(null)
                    }}
                  >
                    Close
                  </Button>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={linkClaimMutation.isPending}
                  >
                    {linkClaimMutation.isPending && (
                      <LoaderCircle className="size-3 animate-spin mr-1" />
                    )}
                    Validate & Bind Claim
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </PageContainer>
  )
}
