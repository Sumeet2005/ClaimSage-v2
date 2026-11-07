import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/features/auth/auth-context'

export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'initializing') {
    return (
      <div
        aria-label="Checking your session"
        className="grid min-h-screen place-items-center bg-ivory-50 p-6"
        role="status"
      >
        <div className="flex items-center gap-3 rounded-2xl border border-ivory-200 bg-white px-5 py-4 text-sm font-medium text-graphite-700 shadow-sm">
          <span className="size-2 animate-pulse rounded-full bg-emerald" />
          Checking your session…
        </div>
      </div>
    )
  }

  if (status !== 'authenticated') {
    return (
      <Navigate
        replace
        state={{ from: location }}
        to="/login"
      />
    )
  }

  return <Outlet />
}
