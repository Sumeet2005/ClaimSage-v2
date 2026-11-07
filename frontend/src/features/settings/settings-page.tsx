import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  HardDrive,
  Layers,
  LoaderCircle,
  Lock,
  RefreshCw,
  Shield,
  User,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageContainer } from '@/components/layout/page-container'
import { getSystemSettings } from '@/features/settings/settings-api'
import { getApiErrorMessage } from '@/features/investigations/investigation-utils'

export function SettingsPage() {
  const { data: settings, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['system-settings'],
    queryFn: getSystemSettings,
  })

  return (
    <PageContainer
      description="Inspect environment settings, AI specialist agent parameters, storage configuration, and live dependency health."
      eyebrow="System & Infrastructure"
      title="Settings & Diagnostics"
    >
      <div className="space-y-6">
        {/* Header Action Bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="relative flex size-2.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex size-2.5 rounded-full bg-emerald-500"></span>
            </span>
            <span className="text-xs font-medium text-graphite-600">
              Environment:{' '}
              <span className="font-semibold uppercase text-emerald-800">
                {settings?.app_env || 'Development'}
              </span>
            </span>
          </div>

          <Button
            className="h-8 gap-1.5 text-xs"
            size="sm"
            variant="outline"
            onClick={() => refetch()}
          >
            <RefreshCw className={`size-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh status
          </Button>
        </div>

        {/* Content State */}
        {isLoading ? (
          <div className="flex min-h-60 flex-col items-center justify-center gap-2 rounded-xl border border-ivory-200 bg-white p-8 text-center shadow-xs">
            <LoaderCircle className="size-6 animate-spin text-emerald-600" />
            <p className="text-xs text-graphite-500">Loading system settings & diagnostics...</p>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50/50 p-6 text-center">
            <AlertTriangle className="mx-auto size-6 text-red-600" />
            <h3 className="mt-2 text-sm font-semibold text-red-900">Failed to load system settings</h3>
            <p className="mt-1 text-xs text-red-600">
              {getApiErrorMessage(error, 'Failed to load system settings.')}
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
        ) : settings ? (
          <div className="space-y-6">
            {/* Service Health Diagnostics */}
            <div>
              <h3 className="text-sm font-semibold text-graphite-900">Live Service Status</h3>
              <p className="text-xs text-graphite-500">
                Direct health diagnostics across connected backend services.
              </p>

              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Card className="border border-ivory-200 bg-white shadow-xs">
                  <CardContent className="pt-5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-graphite-600">PostgreSQL DB</span>
                      <Database className="size-4 text-emerald-600" />
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      <CheckCircle2 className="size-4 text-emerald-600" />
                      <span className="text-sm font-semibold capitalize text-graphite-900">
                        {settings.services.database}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-graphite-500">Relational & audit datastore</p>
                  </CardContent>
                </Card>

                <Card className="border border-ivory-200 bg-white shadow-xs">
                  <CardContent className="pt-5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-graphite-600">MinIO S3 Storage</span>
                      <HardDrive className="size-4 text-emerald-600" />
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      <CheckCircle2 className="size-4 text-emerald-600" />
                      <span className="text-sm font-semibold capitalize text-graphite-900">
                        {settings.services.storage}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-graphite-500">Document & PDF storage</p>
                  </CardContent>
                </Card>

                <Card className="border border-ivory-200 bg-white shadow-xs">
                  <CardContent className="pt-5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-graphite-600">pgvector Extension</span>
                      <Layers className="size-4 text-emerald-600" />
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      <CheckCircle2 className="size-4 text-emerald-600" />
                      <span className="text-sm font-semibold capitalize text-graphite-900">
                        {settings.services.pgvector}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-graphite-500">384-dim semantic embeddings</p>
                  </CardContent>
                </Card>

                <Card className="border border-ivory-200 bg-white shadow-xs">
                  <CardContent className="pt-5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-graphite-600">Investigation Worker</span>
                      <Cpu className="size-4 text-emerald-600" />
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      <CheckCircle2 className="size-4 text-emerald-600" />
                      <span className="text-sm font-semibold capitalize text-graphite-900">
                        {settings.services.worker}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-graphite-500">Background agent dispatch queue</p>
                  </CardContent>
                </Card>
              </div>
            </div>

            {/* AI Specialist Agent Configuration */}
            <Card className="border border-ivory-200 bg-white shadow-xs">
              <CardHeader className="border-b border-ivory-200 pb-3">
                <div className="flex items-center gap-2">
                  <Bot className="size-4 text-emerald-600" />
                  <CardTitle className="text-sm font-semibold text-graphite-900">
                    AI Specialist Agent Configuration
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">LLM Provider</span>
                    <p className="mt-1 text-sm font-semibold uppercase text-graphite-800">
                      {settings.llm_provider}
                    </p>
                  </div>

                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">Active Model</span>
                    <p className="mt-1 font-mono text-sm font-semibold text-emerald-800">
                      {settings.llm_model}
                    </p>
                  </div>

                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">Max Output Tokens</span>
                    <p className="mt-1 text-sm font-semibold text-graphite-800">
                      {settings.llm_max_output_tokens.toLocaleString()} tokens
                    </p>
                  </div>

                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">Inference Timeout</span>
                    <p className="mt-1 text-sm font-semibold text-graphite-800">
                      {settings.llm_timeout_seconds} seconds
                    </p>
                  </div>

                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">Concurrency Limit</span>
                    <p className="mt-1 text-sm font-semibold text-graphite-800">
                      {settings.llm_concurrency_limit} concurrent requests
                    </p>
                  </div>

                  <div className="rounded-lg border border-ivory-200 bg-ivory-50/50 p-3">
                    <span className="text-xs text-graphite-500">Reliability Mode</span>
                    <p className="mt-1 text-sm font-semibold text-purple-700">
                      Adaptive Retry & Token Sharding
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Storage & Communication Security */}
            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="border border-ivory-200 bg-white shadow-xs">
                <CardHeader className="border-b border-ivory-200 pb-3">
                  <div className="flex items-center gap-2">
                    <HardDrive className="size-4 text-emerald-600" />
                    <CardTitle className="text-sm font-semibold text-graphite-900">
                      Object Storage & Evidence
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 pt-4 text-xs">
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Storage Backend:</span>
                    <span className="font-semibold uppercase text-graphite-800">
                      {settings.storage_provider}
                    </span>
                  </div>
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Bucket Name:</span>
                    <span className="font-mono font-medium text-graphite-800">
                      {settings.storage_bucket}
                    </span>
                  </div>
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Endpoint:</span>
                    <span className="font-mono text-graphite-700">
                      {settings.storage_endpoint || 'Configured internal'}
                    </span>
                  </div>
                  <div className="flex justify-between pb-1">
                    <span className="text-graphite-500">Encryption:</span>
                    <span className="font-medium text-emerald-700">Server-Side AES-256</span>
                  </div>
                </CardContent>
              </Card>

              <Card className="border border-ivory-200 bg-white shadow-xs">
                <CardHeader className="border-b border-ivory-200 pb-3">
                  <div className="flex items-center gap-2">
                    <Shield className="size-4 text-emerald-600" />
                    <CardTitle className="text-sm font-semibold text-graphite-900">
                      Security & Communications Policy
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 pt-4 text-xs">
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Email Delivery Mode:</span>
                    <span className="inline-flex items-center gap-1 rounded bg-purple-50 px-1.5 py-0.5 font-medium text-purple-700">
                      <Lock className="size-3" />
                      {settings.email_backend} (Sandbox Safe)
                    </span>
                  </div>
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Default Sender:</span>
                    <span className="font-mono text-graphite-700">
                      {settings.default_sender_email}
                    </span>
                  </div>
                  <div className="flex justify-between border-b border-ivory-100 pb-2">
                    <span className="text-graphite-500">Rate Limiting:</span>
                    <span className="font-medium text-graphite-800">
                      {settings.rate_limit_enabled ? `Active (${settings.rate_limit_per_minute}/min)` : 'Disabled (Local Dev)'}
                    </span>
                  </div>
                  <div className="flex justify-between pb-1">
                    <span className="text-graphite-500">Session JWT Expiry:</span>
                    <span className="font-medium text-graphite-800">
                      {settings.token_expiry_minutes} minutes
                    </span>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Authenticated Employee Session */}
            <Card className="border border-ivory-200 bg-white shadow-xs">
              <CardHeader className="border-b border-ivory-200 pb-3">
                <div className="flex items-center gap-2">
                  <User className="size-4 text-emerald-600" />
                  <CardTitle className="text-sm font-semibold text-graphite-900">
                    Active Session Profile
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                  <div>
                    <span className="text-graphite-500">Employee Name</span>
                    <p className="mt-1 font-semibold text-graphite-800">
                      {settings.current_employee.display_name}
                    </p>
                  </div>
                  <div>
                    <span className="text-graphite-500">Email Address</span>
                    <p className="mt-1 font-mono text-graphite-700">
                      {settings.current_employee.email}
                    </p>
                  </div>
                  <div>
                    <span className="text-graphite-500">Authorization Role</span>
                    <p className="mt-1">
                      <span className="inline-flex rounded-md bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                        {settings.current_employee.role}
                      </span>
                    </p>
                  </div>
                  <div>
                    <span className="text-graphite-500">Assigned Team</span>
                    <p className="mt-1 text-graphite-700">
                      {settings.current_employee.team_id || 'Enterprise Wide (Global)'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        ) : null}
      </div>
    </PageContainer>
  )
}
