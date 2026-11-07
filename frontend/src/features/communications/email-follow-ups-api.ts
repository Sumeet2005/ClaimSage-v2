import { apiClient } from '@/lib/api-client'

export interface EmailFollowUpItem {
  id: string
  source_type: 'customer_email' | 'system_notification' | string
  claim_id?: string | null | undefined
  claim_number?: string | null | undefined
  claimant_name?: string | null | undefined
  investigation_id?: string | null | undefined
  event_type: string
  recipient_email?: string | null | undefined
  recipient_name?: string | null | undefined
  subject?: string | null | undefined
  message_preview?: string | null | undefined
  status: string
  has_secure_upload: boolean
  secure_upload_url?: string | null | undefined
  follow_up_deadline?: string | null | undefined
  attempt_count: number
  last_error_type?: string | null | undefined
  created_at: string
  delivered_at?: string | null | undefined
}

export async function getEmailFollowUps(): Promise<EmailFollowUpItem[]> {
  const { data } = await apiClient.get<EmailFollowUpItem[]>('/claims/emails')
  return data
}
