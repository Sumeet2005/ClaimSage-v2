import { useMemo, useState } from 'react'
import { isAxiosError } from 'axios'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BriefcaseBusiness,
  CalendarDays,
  FileText,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageContainer } from '@/components/layout/page-container'
import { CreateClaimDialog } from '@/features/claims/create-claim-dialog'
import { useClaims } from '@/features/claims/use-claims'
import type { Claim } from '@/types/claims'

type DateSort = 'newest' | 'oldest'
const EMPTY_CLAIMS: Claim[] = []

function formatStatus(status: string) {
  return status.replaceAll('_', ' ')
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date)
}

function getErrorMessage(error: unknown) {
  if (isAxiosError<{ detail?: string }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (!error.response) {
      return 'Unable to reach ClaimSage. Check your connection and try again.'
    }
  }
  return 'Claims could not be loaded. Please try again.'
}

function ClaimLink({ claim }: { claim: Claim }) {
  return (
    <Link
      aria-label={`Open claim ${claim.claim_number}`}
      className="font-semibold text-graphite-900 decoration-emerald/40 underline-offset-4 transition-colors hover:text-emerald-dark hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
      to={`/claims/${claim.id}`}
    >
      {claim.claim_number}
    </Link>
  )
}

function ClaimStatus({ status }: { status: string }) {
  return (
    <Badge className="max-w-full capitalize" variant="secondary">
      <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-emerald" />
      <span className="truncate">{formatStatus(status)}</span>
    </Badge>
  )
}

function ClaimsLoading() {
  return (
    <div aria-label="Loading claims" className="space-y-3" role="status">
      <span className="sr-only">Loading claims</span>
      <Card className="hidden overflow-hidden p-5 md:block">
        <div className="grid grid-cols-4 gap-6">
          {Array.from({ length: 4 }, (_, index) => (
            <div className="h-4 animate-pulse rounded bg-ivory-100" key={index} />
          ))}
        </div>
        <div className="mt-7 space-y-5">
          {Array.from({ length: 5 }, (_, index) => (
            <div className="grid grid-cols-4 gap-6" key={index}>
              {Array.from({ length: 4 }, (_, cellIndex) => (
                <div
                  className="h-5 animate-pulse rounded bg-ivory-100"
                  key={cellIndex}
                />
              ))}
            </div>
          ))}
        </div>
      </Card>
      <div className="space-y-3 md:hidden">
        {Array.from({ length: 3 }, (_, index) => (
          <Card className="space-y-4 p-4" key={index}>
            <div className="h-4 w-2/5 animate-pulse rounded bg-ivory-100" />
            <div className="h-5 w-3/4 animate-pulse rounded bg-ivory-100" />
            <div className="h-4 w-1/2 animate-pulse rounded bg-ivory-100" />
          </Card>
        ))}
      </div>
    </div>
  )
}

function ClaimsError({
  message,
  onRetry,
  isRetrying,
}: {
  message: string
  onRetry: () => void
  isRetrying: boolean
}) {
  return (
    <Card className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-2xl bg-champagne-light text-graphite-700">
        <FileText aria-hidden="true" className="size-5" />
      </span>
      <h2 className="mt-4 font-display text-base font-semibold text-graphite-900">
        Claims are unavailable
      </h2>
      <p className="mt-1 max-w-md text-sm leading-6 text-graphite-600">
        {message}
      </p>
      <Button
        className="mt-5"
        disabled={isRetrying}
        onClick={onRetry}
        variant="outline"
      >
        <RefreshCw aria-hidden="true" className={isRetrying ? 'animate-spin' : ''} />
        Try again
      </Button>
    </Card>
  )
}

function EmptyClaims({
  filtered,
  onCreateClaim,
}: {
  filtered: boolean
  onCreateClaim?: () => void
}) {
  return (
    <Card className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-2xl border border-ivory-200 bg-ivory-50 text-graphite-600">
        <BriefcaseBusiness aria-hidden="true" className="size-5" />
      </span>
      <h2 className="mt-4 font-display text-base font-semibold text-graphite-900">
        {filtered ? 'No matching claims' : 'No claims available'}
      </h2>
      <p className="mt-1 max-w-md text-sm leading-6 text-graphite-600">
        {filtered
          ? 'Try adjusting your search or filters.'
          : 'Claims you are authorized to access will appear here.'}
      </p>
      {!filtered && onCreateClaim && (
        <Button className="mt-4" onClick={onCreateClaim}>
          <Plus className="mr-1.5 size-4" />
          Create First Claim
        </Button>
      )}
    </Card>
  )
}

function SortButton({
  sort,
  onToggle,
}: {
  sort: DateSort
  onToggle: () => void
}) {
  return (
    <button
      aria-label={`Sort by creation date, currently ${sort === 'newest' ? 'newest first' : 'oldest first'}`}
      className="inline-flex items-center gap-1.5 rounded-md text-left font-semibold text-graphite-600 transition-colors hover:text-graphite-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
      onClick={onToggle}
      type="button"
    >
      Created
      {sort === 'newest' ? (
        <ArrowDown aria-hidden="true" className="size-3.5 text-emerald-dark" />
      ) : (
        <ArrowUp aria-hidden="true" className="size-3.5 text-emerald-dark" />
      )}
    </button>
  )
}

function ClaimTable({
  claims,
  sort,
  onToggleSort,
}: {
  claims: Claim[]
  sort: DateSort
  onToggleSort: () => void
}) {
  return (
    <Card className="hidden overflow-hidden md:block">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <thead className="bg-ivory-50/80">
            <tr className="border-b border-ivory-200">
              <th className="px-5 py-3.5 text-xs" scope="col">
                Claim
              </th>
              <th className="px-5 py-3.5 text-xs" scope="col">
                Claimant
              </th>
              <th className="px-5 py-3.5 text-xs" scope="col">
                Type
              </th>
              <th className="px-5 py-3.5 text-xs" scope="col">
                Status
              </th>
              <th className="px-5 py-3.5 text-xs" scope="col">
                <SortButton sort={sort} onToggle={onToggleSort} />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ivory-200/80">
            {claims.map((claim) => (
              <tr
                className="transition-colors hover:bg-ivory-50/80"
                key={claim.id}
              >
                <td className="px-5 py-4 text-sm">
                  <ClaimLink claim={claim} />
                </td>
                <td className="max-w-[240px] truncate px-5 py-4 text-sm text-graphite-700">
                  {claim.claimant_name}
                </td>
                <td className="px-5 py-4 text-sm capitalize text-graphite-700">
                  {formatStatus(claim.claim_type)}
                </td>
                <td className="px-5 py-4">
                  <ClaimStatus status={claim.status} />
                </td>
                <td className="whitespace-nowrap px-5 py-4 text-sm text-graphite-600">
                  {formatDate(claim.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function ClaimCards({ claims }: { claims: Claim[] }) {
  return (
    <div className="space-y-3 md:hidden">
      {claims.map((claim) => (
        <Card className="p-4" key={claim.id}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <ClaimLink claim={claim} />
              <p className="mt-1 truncate text-sm text-graphite-700">
                {claim.claimant_name}
              </p>
            </div>
            <ClaimStatus status={claim.status} />
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-ivory-200 pt-3 text-xs text-graphite-600">
            <span className="capitalize">{formatStatus(claim.claim_type)}</span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays aria-hidden="true" className="size-3.5" />
              {formatDate(claim.created_at)}
            </span>
          </div>
        </Card>
      ))}
    </div>
  )
}

export function ClaimsPage() {
  const { data, error, isError, isPending, isFetching, refetch } = useClaims()
  const [search, setSearch] = useState('')
  const [claimType, setClaimType] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState<DateSort>('newest')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const claims = data ?? EMPTY_CLAIMS

  const claimTypes = useMemo(
    () => [...new Set(claims.map((claim) => claim.claim_type))].sort((a, b) => a.localeCompare(b)),
    [claims],
  )
  const statuses = useMemo(
    () => [...new Set(claims.map((claim) => claim.status))].sort((a, b) => a.localeCompare(b)),
    [claims],
  )

  const filteredClaims = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase()

    return claims
      .filter((claim) => {
        const matchesSearch =
          !normalizedSearch ||
          claim.claim_number.toLocaleLowerCase().includes(normalizedSearch) ||
          claim.claimant_name.toLocaleLowerCase().includes(normalizedSearch)
        const matchesType = !claimType || claim.claim_type === claimType
        const matchesStatus = !status || claim.status === status
        return matchesSearch && matchesType && matchesStatus
      })
      .sort((left, right) => {
        const leftTime = Date.parse(left.created_at)
        const rightTime = Date.parse(right.created_at)
        const leftValid = Number.isNaN(leftTime) ? null : leftTime
        const rightValid = Number.isNaN(rightTime) ? null : rightTime
        if (leftValid === null && rightValid === null) return 0
        if (leftValid === null) return 1
        if (rightValid === null) return -1
        return sort === 'newest' ? rightTime - leftTime : leftTime - rightTime
      })
  }, [claims, claimType, search, sort, status])

  const hasFilters = Boolean(search.trim() || claimType || status)

  return (
    <PageContainer
      actions={
        <Button onClick={() => setIsCreateOpen(true)}>
          <Plus className="mr-1.5 size-4" />
          New Claim
        </Button>
      }
      description="Review the claims available to your account. Access is determined by your workspace authorization."
      eyebrow="Claims workspace"
      title="Claims"
    >
      <section aria-label="Claim search and filters" className="mb-5">
        <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_220px_220px]">
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-graphite-500"
            />
            <Input
              aria-label="Search by claim number or claimant"
              className="h-11 bg-white pl-10"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search claim number or claimant"
              type="search"
              value={search}
            />
          </div>
          <div className="grid grid-cols-[auto_1fr] items-center gap-2.5">
            <Label className="inline-flex items-center gap-1.5 text-xs text-graphite-600" htmlFor="claim-type">
              <SlidersHorizontal aria-hidden="true" className="size-3.5" />
              Type
            </Label>
            <select
              className="h-11 min-w-0 rounded-xl border border-ivory-300 bg-white px-3 text-sm text-graphite-800 transition-colors hover:border-graphite-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/40"
              id="claim-type"
              onChange={(event) => setClaimType(event.target.value)}
              value={claimType}
            >
              <option value="">All types</option>
              {claimTypes.map((type) => (
                <option key={type} value={type}>
                  {formatStatus(type)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-[auto_1fr] items-center gap-2.5">
            <Label className="text-xs text-graphite-600" htmlFor="claim-status">
              Status
            </Label>
            <select
              className="h-11 min-w-0 rounded-xl border border-ivory-300 bg-white px-3 text-sm text-graphite-800 transition-colors hover:border-graphite-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/40"
              id="claim-status"
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              <option value="">All statuses</option>
              {statuses.map((claimStatus) => (
                <option key={claimStatus} value={claimStatus}>
                  {formatStatus(claimStatus)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {isPending ? (
        <ClaimsLoading />
      ) : isError ? (
        <ClaimsError
          isRetrying={isFetching}
          message={getErrorMessage(error)}
          onRetry={() => void refetch()}
        />
      ) : filteredClaims.length === 0 ? (
        <EmptyClaims filtered={hasFilters} onCreateClaim={() => setIsCreateOpen(true)} />
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between text-xs text-graphite-600">
            <p>
              {filteredClaims.length === 1
                ? '1 claim'
                : `${filteredClaims.length} claims`}
              {hasFilters ? ' matching your filters' : ''}
            </p>
            <button
              className="inline-flex items-center gap-1 rounded-md font-medium text-emerald-dark transition-colors hover:text-emerald focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
              onClick={() =>
                setSort((current) =>
                  current === 'newest' ? 'oldest' : 'newest',
                )
              }
              type="button"
            >
              <ArrowUpDown aria-hidden="true" className="size-3.5" />
              {sort === 'newest' ? 'Newest first' : 'Oldest first'}
            </button>
          </div>
          <ClaimTable
            claims={filteredClaims}
            onToggleSort={() =>
              setSort((current) =>
                current === 'newest' ? 'oldest' : 'newest',
              )
            }
            sort={sort}
          />
          <ClaimCards claims={filteredClaims} />
        </>
      )}

      <CreateClaimDialog
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
      />
    </PageContainer>
  )
}
