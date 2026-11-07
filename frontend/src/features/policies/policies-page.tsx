import { useState, type FormEvent } from 'react'
import { isAxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCheck2,
  Filter,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageContainer } from '@/components/layout/page-container'
import { createPolicy, getPolicies } from '@/features/policies/policy-api'
import { useAuth } from '@/features/auth/auth-context'
import type {
  InsuranceType,
  PolicyCreateRequest,
} from '@/types/policies'

function formatStatus(status: string) {
  switch (status) {
    case 'processed':
      return 'Ready / Processed'
    case 'processing':
      return 'Processing'
    case 'uploaded':
      return 'Active / Uploaded'
    case 'failed':
      return 'Failed'
    default:
      return status
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case 'processed':
      return (
        <Badge variant="secondary" className="bg-emerald-50 text-emerald-700 border-emerald-200">
          <CheckCircle2 className="size-3 mr-1" />
          Ready
        </Badge>
      )
    case 'processing':
      return (
        <Badge variant="secondary" className="bg-blue-50 text-blue-700 border-blue-200">
          <LoaderCircle className="size-3 mr-1 animate-spin" />
          Processing
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
          <ShieldAlert className="size-3 mr-1" />
          Failed
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="text-graphite-600">
          {formatStatus(status)}
        </Badge>
      )
  }
}

function formatDate(val: string | null) {
  if (!val) return 'Continuous'
  const d = new Date(val)
  return Number.isNaN(d.getTime()) ? val : d.toLocaleDateString()
}

export function PoliciesPage() {
  const { employee } = useAuth()
  const isAdmin = employee?.role?.toLowerCase() === 'admin'
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchTerm, setSearchTerm] = useState(searchParams.get('search') ?? searchParams.get('query') ?? '')
  const [insuranceTypeFilter, setInsuranceTypeFilter] = useState('health')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 12

  // Create policy modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newIdentifier, setNewIdentifier] = useState('')
  const [newInsurer, setNewInsurer] = useState('')
  const [newProduct, setNewProduct] = useState('')
  const [newType, setNewType] = useState<InsuranceType>('health')
  const [newVersion, setNewVersion] = useState('v1.0')
  const [newEffectiveFrom, setNewEffectiveFrom] = useState('')
  const [newEffectiveTo, setNewEffectiveTo] = useState('')
  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const {
    data: policies,
    isLoading,
    error,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['policies-list', searchTerm, insuranceTypeFilter, statusFilter, page],
    queryFn: () =>
      getPolicies({
        query: searchTerm.trim() || undefined,
        insurance_type: insuranceTypeFilter || undefined,
        status: statusFilter || undefined,
        limit: pageSize,
        offset: page * pageSize,
      }),
  })

  const createMutation = useMutation({
    mutationFn: (payload: PolicyCreateRequest) => createPolicy(payload),
    onSuccess: () => {
      setIsCreateOpen(false)
      resetForm()
      void queryClient.invalidateQueries({ queryKey: ['policies-list'] })
    },
    onError: (err: unknown) => {
      if (isAxiosError<{ detail?: string }>(err)) {
        setFormError(err.response?.data?.detail ?? 'Failed to create policy.')
      } else {
        setFormError('An unexpected error occurred while creating the policy.')
      }
    },
  })

  const resetForm = () => {
    setNewIdentifier('')
    setNewInsurer('')
    setNewProduct('')
    setNewType('health')
    setNewVersion('v1.0')
    setNewEffectiveFrom('')
    setNewEffectiveTo('')
    setNewSourceUrl('')
    setFormError(null)
  }

  const handleCreateSubmit = (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!newIdentifier.trim() || !newInsurer.trim() || !newProduct.trim() || !newEffectiveFrom) {
      setFormError('Please fill in all required fields.')
      return
    }

    if (newEffectiveTo && newEffectiveTo < newEffectiveFrom) {
      setFormError('Effective to date cannot be earlier than effective from date.')
      return
    }

    createMutation.mutate({
      policy_identifier: newIdentifier.trim(),
      insurer_name: newInsurer.trim(),
      product_name: newProduct.trim(),
      insurance_type: newType,
      policy_version: newVersion.trim() || 'v1.0',
      effective_from: newEffectiveFrom,
      effective_to: newEffectiveTo || null,
      source_url: newSourceUrl.trim() || null,
      supported_claim_types: [newType],
    })
  }

  return (
    <PageContainer
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`size-3.5 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {isAdmin && (
            <Button size="sm" onClick={() => setIsCreateOpen(true)}>
              <Plus className="size-4 mr-1.5" />
              New Policy
            </Button>
          )}
        </div>
      }
      breadcrumbs={[
        { label: 'Workspace', href: '/' },
        { label: 'Policies' },
      ]}
      description="Manage insurance policies, coverage terms, benefit limits, exclusions, and document source attachments."
      eyebrow="Policy Administration"
      title="Insurance Policies"
    >
      <div className="space-y-4">
        {/* Search & Filter Bar */}
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[240px] flex-1">
              <Search className="absolute left-3 top-2.5 size-4 text-graphite-400" />
              <Input
                placeholder="Search by policy UIN, insurer, or product name…"
                value={searchTerm}
                onChange={(e) => {
                  const val = e.target.value
                  setSearchTerm(val)
                  setPage(0)
                  if (val.trim()) {
                    setSearchParams({ search: val.trim() })
                  } else {
                    setSearchParams({})
                  }
                }}
                className="pl-9 text-xs"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="size-3.5 text-graphite-500" />
              <select
                value={insuranceTypeFilter}
                onChange={(e) => {
                  setInsuranceTypeFilter(e.target.value)
                  setPage(0)
                }}
                className="rounded-md border border-ivory-300 bg-white px-2.5 py-1.5 text-xs text-graphite-800"
              >
                <option value="health">Health Insurance</option>
                <option value="auto">Motor / Auto</option>
                <option value="property">Property</option>
                <option value="">All Lines</option>
              </select>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value)
                  setPage(0)
                }}
                className="rounded-md border border-ivory-300 bg-white px-2.5 py-1.5 text-xs text-graphite-800"
              >
                <option value="">All Statuses</option>
                <option value="uploaded">Uploaded / Active</option>
                <option value="processed">Ready / Processed</option>
                <option value="processing">Processing</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
        </Card>

        {/* Content Section */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-xs text-graphite-500">
            <LoaderCircle className="size-5 animate-spin mr-2" />
            Loading policies…
          </div>
        ) : error ? (
          <Card className="p-6 text-center text-xs text-rose-700 bg-rose-50 border-rose-200">
            <AlertCircle className="size-5 mx-auto mb-2 text-rose-600" />
            <p className="font-semibold">Unable to load policies.</p>
            <p className="mt-1 text-graphite-600">Please verify your connection and permissions.</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void refetch()}
              className="mt-3 text-xs"
            >
              Try again
            </Button>
          </Card>
        ) : !policies || policies.length === 0 ? (
          <Card className="flex min-h-64 flex-col items-center justify-center p-8 text-center">
            <div className="grid size-12 place-items-center rounded-2xl bg-ivory-100 text-graphite-500 mb-3">
              <ShieldCheck className="size-6 text-emerald" />
            </div>
            <h3 className="font-semibold text-graphite-900 text-sm">No policies found</h3>
            <p className="text-xs text-graphite-500 max-w-sm mt-1">
              {searchTerm || insuranceTypeFilter || statusFilter
                ? 'No insurance policies match your active filter criteria.'
                : 'No policies have been created in the system yet.'}
            </p>
            {isAdmin && (
              <Button
                size="sm"
                onClick={() => setIsCreateOpen(true)}
                className="mt-4 text-xs"
              >
                <Plus className="size-3.5 mr-1" />
                Create First Policy
              </Button>
            )}
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {policies.map((p) => (
              <Card
                key={p.id}
                className="flex flex-col justify-between transition-all hover:border-emerald/40 hover:shadow-sm"
              >
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="text-[10px] uppercase font-mono tracking-wider text-graphite-500">
                        {p.insurance_type ?? 'Health'}
                      </span>
                      <h4 className="font-bold text-graphite-900 text-sm hover:text-emerald-dark">
                        <Link to={`/policies/${p.id}`}>{p.policy_identifier}</Link>
                      </h4>
                    </div>
                    {getStatusBadge(p.status)}
                  </div>
                  <p className="text-xs font-medium text-graphite-700 line-clamp-1 mt-1">
                    {p.product_name || 'Standard Coverage'}
                  </p>
                  <p className="text-[11px] text-graphite-500 line-clamp-1">
                    {p.insurer_name || 'Unknown Insurer'}
                  </p>
                </CardHeader>

                <CardContent className="p-4 pt-2 text-xs space-y-3">
                  <div className="rounded-lg bg-ivory-50 p-2.5 space-y-1 text-[11px] text-graphite-600">
                    <div className="flex items-center justify-between">
                      <span className="text-graphite-500">Version:</span>
                      <span className="font-semibold text-graphite-800">{p.policy_version ?? 'v1.0'}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-graphite-500">Active Window:</span>
                      <span>
                        {formatDate(p.effective_from)} – {formatDate(p.effective_to)}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 font-medium text-blue-700 ring-1 ring-inset ring-blue-700/10">
                      {p.coverage_count} coverages
                    </span>
                    <span className="inline-flex items-center rounded-md bg-amber-50 px-2 py-0.5 font-medium text-amber-700 ring-1 ring-inset ring-amber-700/10">
                      {p.exclusion_count} exclusions
                    </span>
                    {p.has_document_attached ? (
                      <span className="inline-flex items-center rounded-md bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 ring-1 ring-inset ring-emerald-700/10">
                        <FileCheck2 className="size-3 mr-1" />
                        PDF Linked
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-md bg-gray-50 px-2 py-0.5 font-medium text-gray-600 ring-1 ring-inset ring-gray-600/10">
                        Doc Pending
                      </span>
                    )}
                  </div>

                  <div className="pt-2 border-t border-ivory-200 flex items-center justify-end">
                    <Button asChild variant="outline" size="sm" className="h-7 text-xs w-full">
                      <Link to={`/policies/${p.id}`}>
                        View Details & Coverages
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Pagination */}
        {policies && policies.length >= pageSize && (
          <div className="flex items-center justify-between border-t border-ivory-200 pt-3 text-xs text-graphite-600">
            <div>Page {page + 1}</div>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="h-7 px-2 text-xs"
              >
                <ChevronLeft className="size-3 mr-0.5" />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                className="h-7 px-2 text-xs"
              >
                Next
                <ChevronRight className="size-3 ml-0.5" />
              </Button>
            </div>
          </div>
        )}

        {/* Create Policy Dialog Modal */}
        {isCreateOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-ivory-200 pb-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="size-5 text-emerald" />
                  <h3 className="font-bold text-graphite-900 text-base">New Insurance Policy</h3>
                </div>
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="rounded-lg p-1 text-graphite-400 hover:bg-ivory-100 hover:text-graphite-700"
                >
                  <X className="size-4" />
                </button>
              </div>

              {formError && (
                <div className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700 flex items-center gap-2">
                  <AlertCircle className="size-4 shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              <form onSubmit={handleCreateSubmit} className="space-y-3 text-xs">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label className="text-xs">Policy UIN / Identifier *</Label>
                    <Input
                      placeholder="e.g. STAR-FHO-2026"
                      value={newIdentifier}
                      onChange={(e) => setNewIdentifier(e.target.value)}
                      className="mt-1 text-xs"
                      required
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Policy Version *</Label>
                    <Input
                      placeholder="e.g. v1.0"
                      value={newVersion}
                      onChange={(e) => setNewVersion(e.target.value)}
                      className="mt-1 text-xs"
                      required
                    />
                  </div>
                </div>

                <div>
                  <Label className="text-xs">Insurer Name *</Label>
                  <Input
                    placeholder="e.g. Star Health & Allied Insurance Co."
                    value={newInsurer}
                    onChange={(e) => setNewInsurer(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>

                <div>
                  <Label className="text-xs">Product Name *</Label>
                  <Input
                    placeholder="e.g. Family Health Optima Insurance Plan"
                    value={newProduct}
                    onChange={(e) => setNewProduct(e.target.value)}
                    className="mt-1 text-xs"
                    required
                  />
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <Label className="text-xs">Insurance Line</Label>
                    <select
                      value={newType}
                      onChange={(e) => setNewType(e.target.value as InsuranceType)}
                      className="mt-1 w-full rounded-md border border-ivory-300 bg-white px-2 py-1.5 text-xs text-graphite-900"
                    >
                      <option value="health">Health</option>
                      <option value="auto">Motor</option>
                      <option value="property">Property</option>
                    </select>
                  </div>
                  <div>
                    <Label className="text-xs">Effective From *</Label>
                    <Input
                      type="date"
                      value={newEffectiveFrom}
                      onChange={(e) => setNewEffectiveFrom(e.target.value)}
                      className="mt-1 text-xs"
                      required
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Effective To</Label>
                    <Input
                      type="date"
                      value={newEffectiveTo}
                      onChange={(e) => setNewEffectiveTo(e.target.value)}
                      className="mt-1 text-xs"
                    />
                  </div>
                </div>

                <div>
                  <Label className="text-xs">Official Source URL</Label>
                  <Input
                    type="url"
                    placeholder="https://..."
                    value={newSourceUrl}
                    onChange={(e) => setNewSourceUrl(e.target.value)}
                    className="mt-1 text-xs"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-3 border-t border-ivory-200">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsCreateOpen(false)}
                    disabled={createMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" size="sm" disabled={createMutation.isPending}>
                    {createMutation.isPending && (
                      <LoaderCircle className="size-3 animate-spin mr-1.5" />
                    )}
                    Create Policy
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
