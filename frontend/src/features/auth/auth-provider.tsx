import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  getAccessToken,
  registerUnauthorizedHandler,
  setAccessToken,
} from '@/lib/api-client'
import { getCurrentEmployee, loginRequest } from '@/features/auth/auth-api'
import { AuthContext } from '@/features/auth/auth-context'
import type { AuthStatus } from '@/features/auth/auth-context'
import type { CurrentEmployee, LoginRequest } from '@/types/auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<AuthStatus>('initializing')
  const [employee, setEmployee] = useState<CurrentEmployee | null>(null)

  const logout = useCallback(() => {
    setAccessToken(null)
    setEmployee(null)
    setStatus('unauthenticated')
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    let active = true
    const unregisterUnauthorizedHandler =
      registerUnauthorizedHandler(logout)

    const initialize = async () => {
      if (!getAccessToken()) {
        if (active) setStatus('unauthenticated')
        return
      }

      try {
        const currentEmployee = await getCurrentEmployee()
        if (active) {
          setEmployee(currentEmployee)
          setStatus('authenticated')
        }
      } catch {
        if (active) logout()
      }
    }

    void initialize()

    return () => {
      active = false
      unregisterUnauthorizedHandler()
    }
  }, [logout])

  const login = useCallback(
    async (credentials: LoginRequest) => {
      setStatus('initializing')
      let response: Awaited<ReturnType<typeof loginRequest>>
      try {
        response = await loginRequest(credentials)
      } catch (error) {
        setStatus('unauthenticated')
        throw error
      }
      setAccessToken(response.access_token)

      try {
        const currentEmployee = await getCurrentEmployee()
        setEmployee(currentEmployee)
        setStatus('authenticated')
      } catch (error) {
        logout()
        throw error
      }
    },
    [logout],
  )

  const value = useMemo(
    () => ({ status, employee, login, logout }),
    [status, employee, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
