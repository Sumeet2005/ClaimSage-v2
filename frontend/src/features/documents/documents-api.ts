import { apiClient } from '@/lib/api-client'

export interface ClaimEvidenceDocumentItem {
  id: string
  claim_id: string
  claim_number: string
  claimant_name: string
  filename: string
  file_size_bytes: number
  mime_type: string
  storage_status: string
  status: string
  chunk_count: number
  uploaded_at: string
  uploaded_by_name?: string | null | undefined
}

export async function getClaimEvidenceDocuments(): Promise<ClaimEvidenceDocumentItem[]> {
  const { data } = await apiClient.get<ClaimEvidenceDocumentItem[]>('/claims/evidence')
  return data
}

export function formatBytes(bytes: number, decimals = 1): string {
  if (!bytes) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}
