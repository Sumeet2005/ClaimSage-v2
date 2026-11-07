import axios, { type AxiosError } from 'axios'

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

let accessToken: string | null = null
let unauthorizedHandler: (() => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function registerUnauthorizedHandler(handler: () => void) {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.set('Authorization', `Bearer ${accessToken}`)
  } else {
    config.headers.delete('Authorization')
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const requestUrl = error.config?.url ?? ''
    const isLoginRequest = requestUrl.endsWith('/auth/login')

    if (
      error.response?.status === 401 &&
      accessToken !== null &&
      !isLoginRequest
    ) {
      accessToken = null
      unauthorizedHandler?.()
    }

    return Promise.reject(error)
  },
)

export { apiClient }
