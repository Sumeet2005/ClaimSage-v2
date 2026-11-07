import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  FileQuestion,
  Filter,
  Inbox,
  LoaderCircle,
  Mail,
  RefreshCw,
  Search,
  Shield,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageContainer } from '@/components/layout/page-container'
import {
  getEmailFollowUps,
  type EmailFollowUpItem,
} from '@/features/communications/email-follow-ups-api'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'

export function EmailFollowUpsPage() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const { data: items = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['email-follow-ups'],
    queryFn: getEmailFollowUps,
  })

  const filteredItems = items.filter((item) => {
    if (statusFilter !== 'all' && item.status !== statusFilter) return false
    if (typeFilter !== 'all' && item.event_type !== typeFilter) return false
    if (!search) return true
    const term = search.toLowerCase()
    return (
      (item.subject && item.subject.toLowerCase().includes(term)) ||
      (item.recipient_email && item.recipient_email.toLowerCase().includes(term)) ||
      (item.recipient_name && item.recipient_name.toLowerCase().includes(term)) ||
      (item.claim_number && item.claim_number.toLowerCase().includes(term)) ||
      (item.claimant_name && item.claimant_name.toLowerCase().includes(term))
    )
  })

  const totalCount = items.length
  const sandboxedCount = items.filter((i) => i.status === 'sandboxed' || i.status === 'delivered').length
  const draftedCount = items.filter((i) => i.status === 'drafted' || i.status === 'pending').length
  const uploadRequestsCount = items.filter((i) => i.has_secure_upload).length

  const handleCopyLink = (item: EmailFollowUpItem) => {
    if (item.secure_upload_url) {
      navigator.clipboard.writeText(window.location.origin + item.secure_upload_url)
      setCopiedId(item.id)
      setTimeout(() => setCopiedId(null), 2000)
    }
  }

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'sandboxed':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-purple-50 px-2 py-0.5 text-[11px] font-medium text-purple-700 ring-1 ring-inset ring-purple-600/20">
            <Shield className="size-3" />
            Sandboxed
          </span>
        )
      case 'delivered':
      case 'sent':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
            <CheckCircle2 className="size-3" />
            Delivered
          </span>
        )
      case 'drafted':
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20">
            <Clock className="size-3" />
            Draft
          </span>
        )
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-inset ring-red-600/20">
            <AlertCircle className="size-3" />
            Failed
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center rounded-md bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-500/20">
            {status}
          </span>
        )
    }
  }

  const formatEventType = (type: string) => {
    return type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }

  return (
    <PageContainer
      description="Track outbound customer communications, evidence collection requests, and delivery records in safe mode."
      eyebrow="Communications & Outreach"
      title="Email Follow-ups"
    >
      <div className="space-y-6">
        {/* Safe Mode Advisory Banner */}
        <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-xs text-emerald-900 shadow-xs">
          <ShieldCheck className="size-5 shrink-0 text-emerald-700" />
          <div className="flex-1">
            <span className="font-semibold">Safe Sandbox Active:</span> All outgoing customer correspondence and system notifications are preserved in draft or local sandbox state. External emails are never dispatched without explicit configuration.
          </div>
        </div>

        {/* Metric Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Total Communications
              </CardTitle>
              <Inbox className="size-4 text-emerald-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-graphite-900">
                {totalCount}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Recorded messages and notifications</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Sandboxed / Delivered
              </CardTitle>
              <Shield className="size-4 text-purple-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-purple-700">
                {sandboxedCount}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Safely simulated in sandbox outbox</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Pending Drafts
              </CardTitle>
              <Clock className="size-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-amber-700">
                {draftedCount}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Awaiting adjuster review & approval</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Evidence Requests
              </CardTitle>
              <FileQuestion className="size-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-graphite-900">
                {uploadRequestsCount}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Secure document portal follow-ups</p>
            </CardContent>
          </Card>
        </div>

        {/* Filter and Search Bar */}
        <Card className="border border-ivory-200 bg-white p-4 shadow-xs">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-graphite-400" />
              <Input
                className="pl-9 text-sm"
                placeholder="Search recipient, claim number, claimant, or subject..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 text-xs text-graphite-500">
                <Filter className="size-3.5" />
                <span>Filters:</span>
              </div>

              <select
                aria-label="Filter by status"
                className="h-9 rounded-md border border-ivory-300 bg-white px-2.5 py-1 text-xs font-medium text-graphite-700 shadow-xs focus:border-emerald focus:outline-none focus:ring-1 focus:ring-emerald"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="sandboxed">Sandboxed</option>
                <option value="delivered">Delivered</option>
                <option value="drafted">Drafted</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
              </select>

              <select
                aria-label="Filter by event type"
                className="h-9 rounded-md border border-ivory-300 bg-white px-2.5 py-1 text-xs font-medium text-graphite-700 shadow-xs focus:border-emerald focus:outline-none focus:ring-1 focus:ring-emerald"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">All Events</option>
                <option value="investigation_completed">Investigation Completed</option>
                <option value="human_review_required">Human Review Required</option>
                <option value="additional_evidence_required">Additional Evidence Required</option>
                <option value="claim_received">Claim Received</option>
              </select>

              <Button
                className="h-9 gap-1.5 text-xs"
                size="sm"
                variant="outline"
                onClick={() => refetch()}
              >
                <RefreshCw className={`size-3.5 ${isFetching ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>
        </Card>

        {/* Content State */}
        {isLoading ? (
          <div className="flex min-h-60 flex-col items-center justify-center gap-2 rounded-xl border border-ivory-200 bg-white p-8 text-center shadow-xs">
            <LoaderCircle className="size-6 animate-spin text-emerald-600" />
            <p className="text-xs text-graphite-500">Loading communications...</p>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50/50 p-6 text-center">
            <AlertTriangle className="mx-auto size-6 text-red-600" />
            <h3 className="mt-2 text-sm font-semibold text-red-900">Failed to load email follow-ups</h3>
            <p className="mt-1 text-xs text-red-600">
              {getApiErrorMessage(error, 'Failed to load email follow-ups.')}
            </p>
            <Button
              className="mt-4 h-8 text-xs"
              size="sm"
              variant="outline"
              onClick={() => refetch()}
            >
              Try again
            </Button>
          </div>
        ) : filteredItems.length === 0 ? (
          <Card className="flex min-h-56 flex-col items-center justify-center p-8 text-center">
            <Mail className="size-8 text-graphite-400" />
            <h3 className="mt-3 text-sm font-semibold text-graphite-900">No email records found</h3>
            <p className="mt-1 text-xs text-graphite-500">
              {search || statusFilter !== 'all' || typeFilter !== 'all'
                ? 'Try adjusting your search query or filters.'
                : 'No outbound communications have been recorded yet.'}
            </p>
          </Card>
        ) : (
          <div className="space-y-3">
            {filteredItems.map((item) => {
              const isExpanded = expandedId === item.id
              return (
                <Card
                  key={item.id}
                  className="border border-ivory-200 bg-white shadow-xs transition-shadow hover:shadow-sm"
                >
                  <div className="p-4 sm:p-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="space-y-1.5 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          {getStatusBadge(item.status)}
                          <span className="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-inset ring-blue-600/20">
                            {formatEventType(item.event_type)}
                          </span>
                          {item.source_type === 'system_notification' ? (
                            <span className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-600 ring-1 ring-inset ring-gray-500/20">
                              <Bell className="size-2.5" />
                              System Alert
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                              <Mail className="size-2.5" />
                              Customer Email
                            </span>
                          )}
                        </div>

                        <h4 className="text-sm font-semibold text-graphite-900">
                          {item.subject || `Notification: ${formatEventType(item.event_type)}`}
                        </h4>

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-graphite-500">
                          {item.recipient_email && (
                            <span>
                              To: <span className="font-medium text-graphite-700">{item.recipient_name || item.recipient_email}</span>
                            </span>
                          )}
                          {item.claim_number && (
                            <span>
                              Claim:{' '}
                              <Link
                                className="font-medium text-emerald-700 hover:underline"
                                to={`/claims/${item.claim_id}`}
                              >
                                {item.claim_number}
                              </Link>
                            </span>
                          )}
                          {item.claimant_name && (
                            <span>
                              Claimant: <span className="text-graphite-700">{item.claimant_name}</span>
                            </span>
                          )}
                          <span>{new Date(item.created_at).toLocaleString()}</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 self-end sm:self-center">
                        {item.has_secure_upload && item.secure_upload_url && (
                          <Button
                            className="h-8 gap-1.5 text-xs text-emerald-700 hover:bg-emerald-50"
                            size="sm"
                            variant="ghost"
                            onClick={() => handleCopyLink(item)}
                          >
                            <Copy className="size-3.5" />
                            {copiedId === item.id ? 'Copied' : 'Portal link'}
                          </Button>
                        )}
                        <Button
                          className="h-8 gap-1 text-xs text-graphite-600 hover:bg-ivory-100"
                          size="sm"
                          variant="ghost"
                          onClick={() => toggleExpand(item.id)}
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp className="size-3.5" /> Less
                            </>
                          ) : (
                            <>
                              <ChevronDown className="size-3.5" /> Details
                            </>
                          )}
                        </Button>
                      </div>
                    </div>

                    {/* Expandable Preview */}
                    {isExpanded && (
                      <div className="mt-4 border-t border-ivory-200 pt-3 text-xs">
                        <div className="rounded-lg border border-ivory-200 bg-ivory-50/70 p-3">
                          <span className="font-semibold text-graphite-700">Message Content:</span>
                          <p className="mt-1.5 whitespace-pre-wrap leading-relaxed text-graphite-700">
                            {item.message_preview || 'No message body recorded.'}
                          </p>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-graphite-500">
                          <div>
                            ID: <code className="text-graphite-700">{item.id}</code>
                          </div>
                          {item.follow_up_deadline && (
                            <div>
                              Follow-up deadline:{' '}
                              <span className="font-medium text-amber-700">
                                {new Date(item.follow_up_deadline).toLocaleDateString()}
                              </span>
                            </div>
                          )}
                          {item.delivered_at && (
                            <div>
                              Simulated dispatch:{' '}
                              <span className="text-graphite-700">
                                {new Date(item.delivered_at).toLocaleString()}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </PageContainer>
  )
}
