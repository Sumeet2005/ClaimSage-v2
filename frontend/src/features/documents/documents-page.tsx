import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Database,
  Download,
  FileCheck,
  FileStack,
  FileText,
  Filter,
  Layers,
  LoaderCircle,
  RefreshCw,
  Search,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageContainer } from '@/components/layout/page-container'
import {
  formatBytes,
  getClaimEvidenceDocuments,
  type ClaimEvidenceDocumentItem,
} from '@/features/documents/documents-api'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'

export function DocumentsPage() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [storageFilter, setStorageFilter] = useState('all')

  const { data: documents = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['claim-evidence-documents'],
    queryFn: getClaimEvidenceDocuments,
  })

  const filteredDocuments = documents.filter((doc) => {
    if (statusFilter !== 'all' && doc.status !== statusFilter) return false
    if (storageFilter !== 'all' && doc.storage_status !== storageFilter) return false
    if (!search) return true
    const term = search.toLowerCase()
    return (
      doc.filename.toLowerCase().includes(term) ||
      doc.claim_number.toLowerCase().includes(term) ||
      doc.claimant_name.toLowerCase().includes(term)
    )
  })

  const totalDocuments = documents.length
  const storedDocuments = documents.filter((d) => d.storage_status === 'stored').length
  const processedDocuments = documents.filter((d) => d.status === 'processed').length
  const totalChunks = documents.reduce((acc, d) => acc + d.chunk_count, 0)

  const handleDownload = async (doc: ClaimEvidenceDocumentItem) => {
    const url = `/api/v1/claims/${doc.claim_id}/evidence/${doc.id}/download`
    const link = document.createElement('a')
    link.href = url
    link.target = '_blank'
    link.rel = 'noreferrer'
    link.download = doc.filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <PageContainer
      description="Inspect uploaded claim evidence files, extraction chunk counts, processing readiness, and storage status."
      eyebrow="Evidence & Storage"
      title="Evidence Documents"
    >
      <div className="space-y-6">
        {/* Metric Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Total Documents
              </CardTitle>
              <FileStack className="size-4 text-emerald-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-graphite-900">
                {totalDocuments}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Across authorized insurance claims</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Storage Ready
              </CardTitle>
              <Database className="size-4 text-emerald-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-emerald-700">
                {storedDocuments}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Secured in MinIO S3 object store</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Processed For AI
              </CardTitle>
              <FileCheck className="size-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-graphite-900">
                {processedDocuments}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Parsed and vector-embedded</p>
            </CardContent>
          </Card>

          <Card className="border border-ivory-200 bg-white shadow-xs">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-graphite-500">
                Evidence Chunks
              </CardTitle>
              <Layers className="size-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="font-display text-2xl font-semibold text-graphite-900">
                {totalChunks}
              </div>
              <p className="mt-1 text-xs text-graphite-500">Extracted passages for RAG retrieval</p>
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
                placeholder="Search by filename, claim number, or claimant..."
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
                aria-label="Filter by processing status"
                className="h-9 rounded-md border border-ivory-300 bg-white px-2.5 py-1 text-xs font-medium text-graphite-700 shadow-xs focus:border-emerald focus:outline-none focus:ring-1 focus:ring-emerald"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Processing</option>
                <option value="processed">Processed</option>
                <option value="processing">Processing</option>
                <option value="uploaded">Uploaded</option>
                <option value="failed">Failed</option>
              </select>

              <select
                aria-label="Filter by storage status"
                className="h-9 rounded-md border border-ivory-300 bg-white px-2.5 py-1 text-xs font-medium text-graphite-700 shadow-xs focus:border-emerald focus:outline-none focus:ring-1 focus:ring-emerald"
                value={storageFilter}
                onChange={(e) => setStorageFilter(e.target.value)}
              >
                <option value="all">All Storage</option>
                <option value="stored">Stored</option>
                <option value="unavailable">Unavailable</option>
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
            <p className="text-xs text-graphite-500">Loading evidence documents...</p>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50/50 p-6 text-center">
            <AlertTriangle className="mx-auto size-6 text-red-600" />
            <h3 className="mt-2 text-sm font-semibold text-red-900">Failed to load documents</h3>
            <p className="mt-1 text-xs text-red-600">
              {getApiErrorMessage(error, 'Failed to load evidence documents.')}
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
        ) : filteredDocuments.length === 0 ? (
          <Card className="flex min-h-56 flex-col items-center justify-center p-8 text-center">
            <FileText className="size-8 text-graphite-400" />
            <h3 className="mt-3 text-sm font-semibold text-graphite-900">No documents found</h3>
            <p className="mt-1 text-xs text-graphite-500">
              {search || statusFilter !== 'all' || storageFilter !== 'all'
                ? 'Try adjusting your search query or filters.'
                : 'No evidence documents have been uploaded to authorized claims yet.'}
            </p>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredDocuments.map((doc) => (
              <Card
                key={doc.id}
                className="flex flex-col justify-between border border-ivory-200 bg-white shadow-xs transition-shadow hover:shadow-sm"
              >
                <CardHeader className="space-y-2 pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                      <FileText className="size-4" />
                    </span>
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium ${
                          doc.storage_status === 'stored'
                            ? 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20'
                            : 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20'
                        }`}
                      >
                        {doc.storage_status === 'stored' ? (
                          <CheckCircle2 className="size-3" />
                        ) : (
                          <AlertTriangle className="size-3" />
                        )}
                        {doc.storage_status}
                      </span>
                      <span className="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-inset ring-blue-600/20">
                        {doc.status}
                      </span>
                    </div>
                  </div>

                  <div>
                    <h4
                      className="truncate text-sm font-semibold text-graphite-900"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </h4>
                    <p className="mt-0.5 text-xs text-graphite-500">
                      {formatBytes(doc.file_size_bytes)} &bull; {doc.chunk_count} passages extracted
                    </p>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pt-0">
                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-graphite-500">Claim:</span>
                      <Link
                        className="inline-flex items-center gap-1 font-medium text-emerald-700 hover:text-emerald-900 hover:underline"
                        to={`/claims/${doc.claim_id}`}
                      >
                        {doc.claim_number}
                        <ArrowUpRight className="size-3" />
                      </Link>
                    </div>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-graphite-500">Claimant:</span>
                      <span className="font-medium text-graphite-800">{doc.claimant_name}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-graphite-500">Uploaded:</span>
                      <span className="text-graphite-600">
                        {new Date(doc.uploaded_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <span className="text-[11px] text-graphite-500">
                      {doc.uploaded_by_name ? `By ${doc.uploaded_by_name}` : 'System'}
                    </span>
                    <Button
                      className="h-8 gap-1.5 text-xs text-emerald-800 hover:bg-emerald-50"
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDownload(doc)}
                    >
                      <Download className="size-3.5" />
                      Download
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </PageContainer>
  )
}
