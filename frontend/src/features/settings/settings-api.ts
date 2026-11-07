import { apiClient } from '@/lib/api-client'

export interface ServiceHealthItem {
  database: string
  storage: string
  worker: string
  pgvector: string
}

export interface CurrentEmployeeProfile {
  id: string
  display_name: string
  email: string
  role: string
  team_id?: string | null | undefined
}

export interface SystemSettingsResponse {
  app_name: string
  app_env: string
  version: string
  llm_provider: string
  llm_model: string
  llm_max_output_tokens: number
  llm_timeout_seconds: number
  llm_concurrency_limit: number
  storage_provider: string
  storage_bucket: string
  storage_endpoint?: string | null | undefined
  email_backend: string
  default_sender_email: string
  rate_limit_enabled: boolean
  rate_limit_per_minute: number
  token_expiry_minutes: number
  services: ServiceHealthItem
  current_employee: CurrentEmployeeProfile
}

export async function getSystemSettings(): Promise<SystemSettingsResponse> {
  const { data } = await apiClient.get<SystemSettingsResponse>('/system/settings')
  return data
}
