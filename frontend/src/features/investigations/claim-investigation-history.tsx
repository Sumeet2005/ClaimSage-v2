import { AlertCircle, ArrowUpRight, ClipboardList } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  QueryLoading,
  StatusBadge,
} from '@/features/investigations/investigation-components'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'
import { useClaimInvestigations } from '@/features/investigations/use-investigations'

function formattedDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString()
}

export function ClaimInvestigationHistory({ claimId }: { claimId: string }) {
  const query = useClaimInvestigations(claimId)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-light text-emerald-dark">
            <ClipboardList aria-hidden="true" className="size-4" />
          </span>
          <div>
            <CardTitle>Investigation history</CardTitle>
            <p className="mt-1 text-xs leading-5 text-graphite-600">
              Persisted investigation runs and their human-review status.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <QueryLoading label="Loading investigation history…" />
        ) : query.isError ? (
          <div className="rounded-xl border border-ivory-200 bg-ivory-50 p-4" role="alert">
            <p className="flex items-center gap-2 text-sm font-medium text-graphite-800">
              <AlertCircle aria-hidden="true" className="size-4" />
              Investigation history is unavailable
            </p>
            <p className="mt-1 text-xs leading-5 text-graphite-600">
              {getApiErrorMessage(query.error, 'Could not load investigations for this claim.')}
            </p>
            <Button className="mt-3" onClick={() => void query.refetch()} size="sm" variant="outline">
              Try again
            </Button>
          </div>
        ) : query.data.length === 0 ? (
          <p className="rounded-xl bg-ivory-50 p-4 text-sm text-graphite-600">
            No persisted investigations are available for this claim.
          </p>
        ) : (
          <ul className="space-y-2">
            {query.data.map((investigation) => (
              <li
                className="flex flex-col gap-3 rounded-xl border border-ivory-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between"
                key={investigation.id}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className="capitalize" variant="outline">
                      {investigation.claim_domain}
                    </Badge>
                    <StatusBadge value={investigation.status} />
                    <span className="text-[11px] text-graphite-500">
                      Review: {investigation.human_review_status.replaceAll('_', ' ')}
                    </span>
                    {investigation.evidence_sufficiency && (
                      <span className="text-[11px] font-medium text-graphite-700">
                        Evidence: {investigation.evidence_sufficiency.replaceAll('_', ' ')}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-graphite-500">
                    Started {formattedDate(investigation.created_at)}
                    {investigation.report_status &&
                      ` · Report ${investigation.report_status.replaceAll('_', ' ')}`}
                    {investigation.status === 'running' &&
                      ` · Current stage ${
                        investigation.current_stage?.replaceAll('_', ' ') ?? 'starting'
                      }`}
                  </p>
                </div>
                <Button asChild size="sm" variant="outline">
                  <Link to={`/investigations/${investigation.id}`}>
                    Open investigation
                    <ArrowUpRight aria-hidden="true" />
                  </Link>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
