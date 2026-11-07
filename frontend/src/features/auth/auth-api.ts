import { apiClient } from '@/lib/api-client'
import type {
  CurrentEmployee,
  LoginRequest,
  LoginResponse,
} from '@/types/auth'

export async function loginRequest(
  credentials: LoginRequest,
): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>(
    '/auth/login',
    credentials,
  )
  return data
}

export async function getCurrentEmployee(): Promise<CurrentEmployee> {
  const { data } = await apiClient.get<CurrentEmployee>('/auth/me')
  return data
}
