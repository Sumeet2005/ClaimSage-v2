import { isAxiosError } from 'axios'
import { motion } from 'motion/react'
import {
  BriefcaseBusiness,
  Clock3,
  FileText,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { PageContainer } from '@/components/layout/page-container'
import { useClaims } from '@/features/claims/use-claims'
import type { Claim } from '@/types/claims'

function getErrorMessage(error: unknown) {
  if (isAxiosError<{ detail?: string }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (!error.response) {
      return 'Unable to reach ClaimSage. Check your connection and try again.'
    }
  }
  return 'Claim activity could not be loaded. Please try again.'
}

function formatClaimType(claimType: string) {
  if (claimType === 'auto' || claimType === 'motor') return 'Motor'
  return claimType.replaceAll('_', ' ')
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date)
}

function sortNewestFirst(claims: Claim[]) {
  return [...claims].sort((left, right) => {
    const leftTime = Date.parse(left.created_at)
    const rightTime = Date.parse(right.created_at)
    if (Number.isNaN(leftTime)) return Number.isNaN(rightTime) ? 0 : 1
    if (Number.isNaN(rightTime)) return -1
    return rightTime - leftTime
  })
}

export function DashboardPage() {
  const {
    data: claims,
    error,
    isError,
    isFetching,
    isPending,
    refetch,
  } = useClaims()
  const authorizedClaims = claims ?? []
  const motorCount = authorizedClaims.filter(
    (claim) => claim.claim_type === 'auto' || claim.claim_type === 'motor',
  ).length
  const healthCount = authorizedClaims.filter(
    (claim) => claim.claim_type === 'health',
  ).length
  const overviewItems = [
    {
      label: 'Claims available',
      value: String(authorizedClaims.length),
      detail: 'Claims you are authorized to access',
      icon: BriefcaseBusiness,
      tone: 'emerald',
    },
    {
      label: 'Motor claims',
      value: String(motorCount),
      detail: 'Auto and motor insurance',
      icon: FileText,
      tone: 'champagne',
    },
    {
      label: 'Health claims',
      value: String(healthCount),
      detail: 'Health insurance',
      icon: ShieldCheck,
      tone: 'graphite',
    },
  ] as const
  const recentClaims = sortNewestFirst(authorizedClaims).slice(0, 5)

  return (
    <PageContainer
      actions={
        <Link
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-emerald/25 bg-emerald-light px-4 py-2 text-sm font-semibold text-emerald-dark transition-colors hover:bg-emerald-light/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
          to="/claims"
        >
          <BriefcaseBusiness aria-hidden="true" className="size-4" />
          Open claims
        </Link>
      }
      description="A considered view of the claims and reviews available to your account."
      eyebrow="Investigation workspace"
      title="Your claims, in context."
    >
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        initial={{ opacity: 0, y: 10 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <section
          aria-label="Claim workspace overview"
          className="grid gap-4 md:grid-cols-3"
        >
          {overviewItems.map(({ label, value, detail, icon: Icon, tone }, index) => (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              key={label}
              transition={{ delay: 0.06 * (index + 1), duration: 0.3 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
            >
              <Card className="h-full">
                <CardContent className="flex items-start justify-between p-4 sm:p-5">
                  <div>
                    <p className="text-sm font-medium text-graphite-600">{label}</p>
                    <p
                      aria-label={isPending ? `${label} loading` : undefined}
                      className="mt-3 font-display text-4xl font-medium tracking-[-0.06em] text-graphite-950"
                    >
                      {isPending ? '—' : isError ? '!' : value}
                    </p>
                    <p className="mt-2 text-xs text-graphite-600">{detail}</p>
                  </div>
                  <span
                    className={
                      tone === 'emerald'
                        ? 'grid size-10 place-items-center rounded-xl bg-emerald-light text-emerald-dark'
                        : tone === 'champagne'
                          ? 'grid size-10 place-items-center rounded-xl bg-champagne-light text-graphite-700'
                          : 'grid size-10 place-items-center rounded-xl bg-ivory-100 text-graphite-600'
                    }
                  >
                    <Icon aria-hidden="true" className="size-[18px]" />
                  </span>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[1.45fr_0.85fr]">
          <Card className="min-h-[310px]">
            <CardHeader className="flex-row items-start justify-between space-y-0 p-4 sm:p-5">
              <div>
                <CardTitle>Recent claims</CardTitle>
                <CardDescription className="mt-1 text-graphite-600">
                  Latest claims available to your account.
                </CardDescription>
              </div>
              <Link
                className="rounded-md px-2 py-1 text-xs font-semibold text-emerald-dark transition-colors hover:text-emerald focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
                to="/claims"
              >
                View all
              </Link>
            </CardHeader>
            <CardContent>
              {isPending ? (
                <div
                  aria-label="Loading recent claims"
                  className="flex min-h-[185px] items-center justify-center rounded-2xl bg-ivory-50 text-sm text-graphite-500"
                  role="status"
                >
                  Loading claims…
                </div>
              ) : isError ? (
                <div
                  className="flex min-h-[185px] flex-col items-center justify-center rounded-2xl border border-red-200 bg-red-50 px-6 text-center"
                  role="alert"
                >
                  <p className="max-w-md text-sm leading-6 text-graphite-700">
                    {getErrorMessage(error)}
                  </p>
                  <Button
                    className="mt-3"
                    disabled={isFetching}
                    onClick={() => void refetch()}
                    size="sm"
                    variant="outline"
                  >
                    <RefreshCw
                      aria-hidden="true"
                      className={isFetching ? 'animate-spin' : ''}
                    />
                    Try again
                  </Button>
                </div>
              ) : recentClaims.length === 0 ? (
                <div className="flex min-h-[185px] flex-col items-center justify-center rounded-2xl border border-dashed border-ivory-300 bg-ivory-50/70 px-6 text-center">
                  <span className="grid size-11 place-items-center rounded-2xl border border-ivory-200 bg-white text-graphite-600 shadow-sm">
                    <BriefcaseBusiness aria-hidden="true" className="size-5" />
                  </span>
                  <h2 className="mt-4 font-display text-base font-semibold text-graphite-900">
                    No claims available
                  </h2>
                  <p className="mt-1 max-w-sm text-xs leading-5 text-graphite-600">
                    Claims you are authorized to access will appear here.
                  </p>
                </div>
              ) : (
                <ul className="divide-y divide-ivory-200">
                  {recentClaims.map((claim) => (
                    <li className="py-3 first:pt-1 last:pb-1" key={claim.id}>
                      <Link
                        className="flex flex-wrap items-center justify-between gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-ivory-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
                        to={`/claims/${claim.id}`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-graphite-900">
                            {claim.claim_number}
                          </span>
                          <span className="mt-1 block truncate text-xs text-graphite-600">
                            {claim.claimant_name} · {formatClaimType(claim.claim_type)}
                          </span>
                        </span>
                        <span className="text-right">
                          <span className="block text-xs capitalize text-graphite-700">
                            {claim.status.replaceAll('_', ' ')}
                          </span>
                          <span className="mt-1 block text-[11px] text-graphite-500">
                            {formatDate(claim.created_at)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader className="p-4 sm:p-5">
              <div className="flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-lg bg-champagne-light text-graphite-700">
                  <ShieldCheck aria-hidden="true" className="size-4" />
                </span>
                <CardTitle>Review principles</CardTitle>
              </div>
              <CardDescription className="text-graphite-600">
                Clear boundaries for every investigation.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5 p-4 pt-0 sm:p-5 sm:pt-0">
              {[
                'Evidence stays connected to its source.',
                'Uncertainty is surfaced, not hidden.',
                'People make every consequential decision.',
              ].map((item, index) => (
                <div
                  className="flex items-start gap-3 rounded-xl border border-ivory-200/80 bg-ivory-50/70 p-3"
                  key={item}
                >
                  <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-emerald-light font-display text-[10px] font-semibold text-emerald-dark">
                    0{index + 1}
                  </span>
                  <p className="text-xs leading-5 text-graphite-700">{item}</p>
                </div>
              ))}
              <div className="rounded-xl border border-champagne/25 bg-champagne-light/60 p-3">
                <div className="flex items-center gap-2 text-graphite-800">
                  <Clock3 aria-hidden="true" className="size-4 text-champagne" />
                  <p className="text-xs font-semibold">Human review is mandatory</p>
                </div>
                <p className="mt-2 text-xs leading-5 text-graphite-600">
                  ClaimSage assists with investigation and reporting. It does not
                  approve, deny or decide coverage.
                </p>
              </div>
            </CardContent>
          </Card>
        </section>

        <footer className="mt-6 flex flex-col gap-2 border-t border-ivory-200 pt-4 text-[11px] text-graphite-600 sm:flex-row sm:items-center sm:justify-between">
          <span>ClaimSage · Investigation support for insurance teams</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-emerald" />
            Human judgment remains central
          </span>
        </footer>
      </motion.div>
    </PageContainer>
  )
}
