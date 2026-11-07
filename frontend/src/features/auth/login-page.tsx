import { zodResolver } from '@hookform/resolvers/zod'
import { AnimatePresence, motion } from 'motion/react'
import { AlertCircle, ArrowRight, LockKeyhole, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/features/auth/auth-context'
import { cn } from '@/lib/utils'
import type { LoginRequest } from '@/types/auth'
import { isAxiosError } from 'axios'

const loginSchema = z.object({
  email: z
    .string()
    .trim()
    .min(3, 'Enter your work email.')
    .max(320, 'Email must be 320 characters or fewer.')
    .regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Enter a valid email address.'),
  password: z
    .string()
    .min(1, 'Enter your password.')
    .max(256, 'Password must be 256 characters or fewer.'),
})

type LoginFormValues = z.infer<typeof loginSchema>

function getLoginErrorMessage(error: unknown) {
  if (isAxiosError<{ detail?: string }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (!error.response) {
      return 'Unable to reach ClaimSage. Check your connection and try again.'
    }
  }
  return 'Unable to sign in. Please try again.'
}

function BrandMark() {
  return (
    <span className="grid size-11 place-items-center rounded-2xl bg-emerald text-ivory-50 shadow-[0_8px_24px_-10px_rgba(40,93,66,0.65)]">
      <ShieldCheck aria-hidden="true" className="size-[22px]" strokeWidth={1.8} />
    </span>
  )
}

export function LoginPage() {
  const { login, status } = useAuth()
  const location = useLocation()
  const [requestError, setRequestError] = useState<string | null>(null)
  const from = (location.state as { from?: { pathname?: string } } | null)?.from
    ?.pathname

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  if (status === 'authenticated') {
    return <Navigate replace to={from || '/'} />
  }

  const onSubmit = async (values: LoginFormValues) => {
    setRequestError(null)
    try {
      const credentials: LoginRequest = {
        email: values.email.trim().toLowerCase(),
        password: values.password,
      }
      await login(credentials)
    } catch (error) {
      setRequestError(getLoginErrorMessage(error))
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-ivory-50 text-graphite-900">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-40 -top-40 size-[520px] rounded-full border border-champagne/20"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 -top-20 size-[360px] rounded-full border border-emerald/10"
      />

      <div className="relative mx-auto grid min-h-screen w-full max-w-[1440px] lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden flex-col justify-between bg-graphite-950 px-12 py-10 text-ivory-50 lg:flex xl:px-20">
          <Link
            aria-label="ClaimSage home"
            className="inline-flex w-fit items-center gap-3 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ivory-50"
            to="/login"
          >
            <BrandMark />
            <span className="font-display text-xl font-semibold tracking-[-0.045em]">
              ClaimSage
            </span>
          </Link>

          <div className="max-w-xl pb-8">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-champagne/25 bg-champagne/10 px-3 py-1.5 text-[11px] font-medium tracking-wide text-champagne-light">
              <LockKeyhole aria-hidden="true" className="size-3.5" />
              PRIVATE INVESTIGATION WORKSPACE
            </div>
            <h1 className="font-display text-5xl font-medium leading-[1.08] tracking-[-0.055em] xl:text-[60px]">
              Clarity for
              <br />
              complex claims.
            </h1>
            <p className="mt-6 max-w-md text-sm leading-7 text-graphite-300">
              Review evidence with care, keep every source in context, and leave
              consequential decisions where they belong—with people.
            </p>
            <div className="mt-10 flex items-center gap-3 border-t border-white/10 pt-5 text-xs text-graphite-300">
              <span className="grid size-8 place-items-center rounded-lg bg-white/[0.06] text-champagne-light">
                <ShieldCheck aria-hidden="true" className="size-4" />
              </span>
              Human review remains mandatory
            </div>
          </div>

          <p className="text-[11px] text-graphite-400">
            ClaimSage · Investigation support for insurance teams
          </p>
        </section>

        <section className="flex min-h-screen flex-col px-5 py-7 sm:px-10 lg:px-14 xl:px-20">
          <div className="flex items-center justify-between lg:justify-end">
            <Link
              aria-label="ClaimSage home"
              className="inline-flex items-center gap-2.5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald lg:hidden"
              to="/login"
            >
              <BrandMark />
              <span className="font-display text-lg font-semibold tracking-[-0.04em] text-graphite-950">
                ClaimSage
              </span>
            </Link>
            <span className="text-xs text-graphite-600">
              Need access? Contact your workspace administrator.
            </span>
          </div>

          <div className="flex flex-1 items-center justify-center py-10">
            <div className="w-full max-w-[420px]">
              <div className="mb-7">
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-dark">
                  Secure sign in
                </p>
                <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.045em] text-graphite-950 sm:text-[36px]">
                  Welcome back
                </h2>
                <p className="mt-2 text-sm leading-6 text-graphite-600">
                  Sign in with your ClaimSage employee account.
                </p>
              </div>

              <Card className="border-ivory-200/90 p-5 shadow-[0_20px_60px_-38px_rgba(25,28,25,0.34)] sm:p-7">
                <form
                  className="space-y-5"
                  noValidate
                  onSubmit={handleSubmit(onSubmit)}
                >
                  <div className="space-y-2">
                    <Label htmlFor="email">Work email</Label>
                    <Input
                      autoComplete="username"
                      autoCapitalize="none"
                      aria-describedby={errors.email ? 'email-error' : undefined}
                      aria-invalid={Boolean(errors.email)}
                      className={cn(
                        'h-11',
                        errors.email && 'border-graphite-700 focus-visible:ring-graphite-400/30',
                      )}
                      id="email"
                      placeholder="name@company.com"
                      type="email"
                      {...register('email')}
                    />
                    {errors.email && (
                      <p className="text-xs font-medium text-graphite-700" id="email-error">
                        {errors.email.message}
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="password">Password</Label>
                    <Input
                      autoComplete="current-password"
                      aria-describedby={
                        errors.password ? 'password-error' : undefined
                      }
                      aria-invalid={Boolean(errors.password)}
                      className={cn(
                        'h-11',
                        errors.password && 'border-graphite-700 focus-visible:ring-graphite-400/30',
                      )}
                      id="password"
                      placeholder="Enter your password"
                      type="password"
                      {...register('password')}
                    />
                    {errors.password && (
                      <p className="text-xs font-medium text-graphite-700" id="password-error">
                        {errors.password.message}
                      </p>
                    )}
                  </div>

                  <AnimatePresence initial={false}>
                    {requestError && (
                      <motion.div
                        animate={{ opacity: 1, height: 'auto' }}
                        className="flex items-start gap-2.5 rounded-xl border border-champagne/40 bg-champagne-light/60 px-3.5 py-3 text-sm text-graphite-800"
                        exit={{ opacity: 0, height: 0 }}
                        initial={{ opacity: 0, height: 0 }}
                        role="alert"
                      >
                        <AlertCircle
                          aria-hidden="true"
                          className="mt-0.5 size-4 shrink-0 text-graphite-700"
                        />
                        <span>{requestError}</span>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <Button
                    className="h-11 w-full justify-between px-4"
                    disabled={isSubmitting}
                    type="submit"
                  >
                    <span>
                      {isSubmitting ? 'Signing in…' : 'Sign in securely'}
                    </span>
                    <ArrowRight aria-hidden="true" />
                  </Button>
                </form>

                <div className="mt-5 flex items-center justify-center gap-2 border-t border-ivory-200 pt-4 text-[11px] text-graphite-600">
                  <LockKeyhole aria-hidden="true" className="size-3.5" />
                  Your session stays in memory on this device.
                </div>
              </Card>

              <p className="mt-6 text-center text-xs leading-5 text-graphite-600">
                ClaimSage supports investigation and reporting. It does not
                make claim decisions.
              </p>
            </div>
          </div>

          <p className="text-center text-[11px] text-graphite-500 lg:text-right">
            Human review is always required
          </p>
        </section>
      </div>
    </main>
  )
}
