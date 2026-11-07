import { Suspense, lazy } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { ArrowUpRight } from 'lucide-react'
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useParams,
} from 'react-router-dom'
import { Toaster } from 'sonner'
import { navigationItems } from '@/components/navigation/navigation-items'
import { PageContainer } from '@/components/layout/page-container'
import { Card } from '@/components/ui/card'
import { queryClient } from '@/lib/query-client'
import { AuthProvider } from '@/features/auth/auth-provider'
import { ProtectedRoute } from '@/features/auth/protected-route'

const DashboardPage = lazy(() =>
  import('@/features/dashboard/dashboard-page').then((module) => ({
    default: module.DashboardPage,
  })),
)

const ClaimsPage = lazy(() =>
  import('@/features/claims/claims-page').then((module) => ({
    default: module.ClaimsPage,
  })),
)

const ClaimDetailPage = lazy(() =>
  import('@/features/claims/claim-detail-page').then((module) => ({
    default: module.ClaimDetailPage,
  })),
)

const PoliciesPage = lazy(() =>
  import('@/features/policies/policies-page').then((module) => ({
    default: module.PoliciesPage,
  })),
)

const PolicyDetailPage = lazy(() =>
  import('@/features/policies/policy-detail-page').then((module) => ({
    default: module.PolicyDetailPage,
  })),
)

const InvestigationDetailPage = lazy(() =>
  import('@/features/investigations/investigation-detail-page').then((module) => ({
    default: module.InvestigationDetailPage,
  })),
)

const InvestigationsPage = lazy(() =>
  import('@/features/investigations/investigations-page').then((module) => ({
    default: module.InvestigationsPage,
  })),
)

const ReviewQueuePage = lazy(() =>
  import('@/features/investigations/review-queue-page').then((module) => ({
    default: module.ReviewQueuePage,
  })),
)

const AuditLogsPage = lazy(() =>
  import('@/features/audit/audit-logs-page').then((module) => ({
    default: module.AuditLogsPage,
  })),
)

const DocumentsPage = lazy(() =>
  import('@/features/documents/documents-page').then((module) => ({
    default: module.DocumentsPage,
  })),
)

const EmailFollowUpsPage = lazy(() =>
  import('@/features/communications/email-follow-ups-page').then((module) => ({
    default: module.EmailFollowUpsPage,
  })),
)

const SettingsPage = lazy(() =>
  import('@/features/settings/settings-page').then((module) => ({
    default: module.SettingsPage,
  })),
)

const AppShell = lazy(() =>
  import('@/app/app-shell').then((module) => ({
    default: module.AppShell,
  })),
)

const LoginPage = lazy(() =>
  import('@/features/auth/login-page').then((module) => ({
    default: module.LoginPage,
  })),
)

function PageLoading() {
  return (
    <div
      aria-label="Loading page"
      className="min-h-[40vh] animate-pulse rounded-2xl bg-ivory-100"
      role="status"
    />
  )
}

function NotFoundPage() {
  return (
    <PageContainer
      description="ClaimSage is being prepared. Return to the dashboard to continue."
      title="This page is not here yet"
    >
      <Card className="flex min-h-56 flex-col items-center justify-center text-center">
        <p className="font-display text-sm font-semibold tracking-[0.22em] text-emerald">
          404
        </p>
      </Card>
    </PageContainer>
  )
}

function WorkspaceSectionPage() {
  const { section } = useParams()
  const item = navigationItems.find(
    (navigationItem) => navigationItem.href === `/${section}`,
  )

  if (!item) return <NotFoundPage />

  const Icon = item.icon

  return (
    <PageContainer
      description={`${item.label} tools will be available here when this workspace area is connected.`}
      eyebrow="Workspace"
      title={item.label}
    >
      <Card className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
        <span className="grid size-12 place-items-center rounded-2xl border border-ivory-200 bg-ivory-50 text-emerald-dark">
          <Icon aria-hidden="true" className="size-5" />
        </span>
        <h2 className="mt-4 font-display text-base font-semibold text-graphite-900">
          {item.label} workspace
        </h2>
        <p className="mt-1 max-w-md text-sm leading-6 text-graphite-500">
          This frontend preview is not connected to business data or backend
          services.
        </p>
        <Link
          className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-dark transition-colors hover:text-emerald focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
          to="/"
        >
          Return to dashboard
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
        </Link>
      </Card>
    </PageContainer>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route
              path="login"
              element={
                <Suspense fallback={<PageLoading />}>
                  <LoginPage />
                </Suspense>
              }
            />
            <Route element={<ProtectedRoute />}>
              <Route
                element={
                  <Suspense fallback={<PageLoading />}>
                    <AppShell />
                  </Suspense>
                }
              >
                <Route
                  index
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <DashboardPage />
                    </Suspense>
                  }
                />
                <Route path="dashboard" element={<Navigate to="/" replace />} />
                <Route
                  path="claims"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <ClaimsPage />
                    </Suspense>
                  }
                />
                <Route
                  path="claims/:claimId"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <ClaimDetailPage />
                    </Suspense>
                  }
                />
                <Route
                  path="policies"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <PoliciesPage />
                    </Suspense>
                  }
                />
                <Route
                  path="policies/:policyId"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <PolicyDetailPage />
                    </Suspense>
                  }
                />
                <Route
                  path="investigations"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <InvestigationsPage />
                    </Suspense>
                  }
                />
                <Route
                  path="investigations/:investigationId"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <InvestigationDetailPage />
                    </Suspense>
                  }
                />
                <Route
                  path="review-queue"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <ReviewQueuePage />
                    </Suspense>
                  }
                />
                <Route
                  path="documents"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <DocumentsPage />
                    </Suspense>
                  }
                />
                <Route
                  path="email-follow-ups"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <EmailFollowUpsPage />
                    </Suspense>
                  }
                />
                <Route
                  path="audit-logs"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <AuditLogsPage />
                    </Suspense>
                  }
                />
                <Route
                  path="settings"
                  element={
                    <Suspense fallback={<PageLoading />}>
                      <SettingsPage />
                    </Suspense>
                  }
                />
                <Route path=":section" element={<WorkspaceSectionPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <Toaster
        position="bottom-right"
        toastOptions={{
          classNames: {
            toast: 'border border-ivory-300 bg-ivory-50 text-graphite-900',
          },
        }}
      />
    </QueryClientProvider>
  )
}

export default App
