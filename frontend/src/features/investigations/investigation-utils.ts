import { isAxiosError } from 'axios'

export function getApiErrorMessage(error: unknown, fallback: string) {
  if (isAxiosError<{ detail?: unknown }>(error)) {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    if (status === 401 || status === 403) {
      return 'Your account is not authorized to view or review this investigation.'
    }
    if (status === 404) {
      return 'This investigation is unavailable to your account.'
    }
    if (typeof detail === 'string') return detail
    if (!error.response) return 'Unable to reach ClaimSage. Check your connection.'
  }
  return fallback
}
