import {
  AnimatePresence,
  MotionConfig,
  motion,
  useReducedMotion,
} from 'motion/react'
import {
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { Dropdown, DropdownLink } from '@/components/ui/dropdown'
import { Input } from '@/components/ui/input'
import { Tooltip } from '@/components/ui/tooltip'
import { MainNavigation } from '@/components/navigation/main-navigation'
import { navigationItems } from '@/components/navigation/navigation-items'
import { cn } from '@/lib/utils'
import { useAuth } from '@/features/auth/auth-context'

function getInitials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? '')
    .join('')
    .toUpperCase()
}

function formatRole(role: string) {
  const normalized = role.toLowerCase().replace(/[\s-]+/g, '_')
  if (normalized === 'claims_adjuster' || normalized === 'claims_analyst') {
    return 'Claims Analyst'
  }
  if (normalized === 'admin') {
    return 'Admin'
  }
  return role.replaceAll('_', ' ')
}

function BrandMark() {
  return (
    <span
      aria-hidden="true"
      className="grid size-9 shrink-0 place-items-center rounded-xl bg-emerald text-ivory-50 shadow-sm"
    >
      <ShieldCheck className="size-5" strokeWidth={1.8} />
    </span>
  )
}

function Sidebar({
  collapsed,
  mobile = false,
  onNavigate,
  onClose,
}: {
  collapsed: boolean
  mobile?: boolean
  onNavigate?: () => void
  onClose?: () => void
}) {
  const { employee } = useAuth()

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className={cn(
          'flex h-11 shrink-0 items-center',
          collapsed && !mobile ? 'justify-center' : 'justify-between',
        )}
      >
        <Link
          aria-label="ClaimSage dashboard"
          className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ivory-50"
          onClick={onNavigate}
          to="/dashboard"
        >
          <BrandMark />
          {(!collapsed || mobile) && (
            <span className="font-display text-[19px] font-semibold tracking-[-0.04em] text-ivory-50">
              ClaimSage
            </span>
          )}
        </Link>
        {mobile && (
          <button
            aria-label="Close navigation"
            className="grid size-9 place-items-center rounded-xl text-graphite-400 transition-colors hover:bg-white/10 hover:text-ivory-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ivory-50"
            onClick={onClose}
            type="button"
          >
            <X aria-hidden="true" className="size-[18px]" />
          </button>
        )}
      </div>

      <MainNavigation
        collapsed={collapsed && !mobile}
        className="mt-9 min-h-0 flex-1 overflow-y-auto"
        {...(onNavigate ? { onNavigate } : {})}
      />

      <div className={cn('mt-5 border-t border-white/10 pt-5', collapsed && !mobile && 'px-0')}>
        {collapsed && !mobile ? (
          <Tooltip label="Human review is mandatory">
            {(props) => (
              <span
                aria-label="Human review is mandatory"
                className="mx-auto grid size-10 place-items-center rounded-xl bg-champagne/15 text-champagne-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ivory-50"
                tabIndex={0}
                {...props}
              >
                <ShieldCheck aria-hidden="true" className="size-[18px]" />
              </span>
            )}
          </Tooltip>
        ) : (
          <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
            <div className="flex size-8 items-center justify-center rounded-lg bg-champagne/15 text-champagne-light">
              <ShieldCheck aria-hidden="true" className="size-4" />
            </div>
            <p className="mt-3 text-sm font-medium text-ivory-50">
              Human review, always
            </p>
            <p className="mt-1 text-xs leading-5 text-graphite-400">
              Decisions stay with people. ClaimSage supports careful investigation.
            </p>
          </div>
        )}
        {(!collapsed || mobile) && (
          <div className="mt-5 flex items-center gap-3 rounded-xl px-2 py-2">
            <span className="grid size-9 shrink-0 place-items-center rounded-full border border-champagne/40 bg-champagne/10 font-display text-xs font-semibold text-champagne-light">
              {employee ? getInitials(employee.display_name) : ''}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-ivory-50">
                {employee?.display_name}
              </span>
              <span className="mt-0.5 block text-xs text-graphite-400">
                {employee ? formatRole(employee.role) : ''}
              </span>
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

function getCurrentPage(pathname: string) {
  return navigationItems.find((item) =>
    item.href === '/'
      ? pathname === '/'
      : pathname === item.href || pathname.startsWith(`${item.href}/`),
  )
}

export function AppShell() {
  const { employee, logout } = useAuth()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const mobileSidebarRef = useRef<HTMLElement>(null)
  const location = useLocation()
  const reduceMotion = useReducedMotion()
  const currentPage = getCurrentPage(location.pathname)

  useEffect(() => {
    if (!mobileMenuOpen) return

    const menuTrigger = menuTriggerRef.current
    mobileSidebarRef.current
      ?.querySelector<HTMLButtonElement>('[aria-label="Close navigation"]')
      ?.focus()

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setMobileMenuOpen(false)
        return
      }
      if (event.key !== 'Tab' || !mobileSidebarRef.current) return

      const focusable = Array.from(
        mobileSidebarRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      menuTrigger?.focus()
    }
  }, [mobileMenuOpen])

  const handleMobileKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') setMobileMenuOpen(false)
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen bg-ivory-50 text-graphite-900">
      <motion.aside
        animate={{ width: sidebarCollapsed ? 80 : 272 }}
        className="fixed inset-y-0 left-0 z-30 hidden flex-col bg-graphite-950 px-4 py-6 lg:flex"
        initial={false}
        transition={{ duration: reduceMotion ? 0 : 0.24, ease: 'easeInOut' }}
      >
        <Sidebar collapsed={sidebarCollapsed} />
        <p
          className={cn(
            'mt-4 text-center text-[10px] leading-4 text-graphite-400',
            sidebarCollapsed && 'sr-only',
          )}
        >
          Built for thoughtful investigation
        </p>
      </motion.aside>

      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            animate={{ opacity: 1 }}
            className="fixed inset-0 z-50 lg:hidden"
            exit={{ opacity: 0 }}
            initial={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.18 }}
          >
            <button
              aria-label="Close navigation"
              className="absolute inset-0 cursor-default bg-graphite-950/60 backdrop-blur-[2px]"
              onClick={() => setMobileMenuOpen(false)}
              tabIndex={-1}
              type="button"
            />
            <motion.aside
              ref={mobileSidebarRef}
              aria-label="Mobile navigation"
              aria-modal="true"
              animate={{ x: 0 }}
              className="absolute inset-y-0 left-0 w-[min(86vw,320px)] bg-graphite-950 px-5 py-6 shadow-2xl"
              exit={{ x: '-100%' }}
              initial={{ x: '-100%' }}
              onKeyDown={handleMobileKeyDown}
              role="dialog"
              transition={{ duration: reduceMotion ? 0 : 0.22, ease: 'easeOut' }}
            >
              <Sidebar
                collapsed={false}
                mobile
                onClose={() => setMobileMenuOpen(false)}
                onNavigate={() => setMobileMenuOpen(false)}
              />
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <div
        className={cn(
          'min-h-screen transition-[padding] duration-300 ease-in-out',
          sidebarCollapsed ? 'lg:pl-20' : 'lg:pl-[272px]',
          reduceMotion && 'lg:transition-none',
        )}
      >
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-ivory-200/80 bg-ivory-50/90 px-4 backdrop-blur-xl sm:gap-5 sm:px-7 lg:px-9">
          <div className="flex shrink-0 items-center gap-2">
            <button
              aria-label="Open navigation"
              className="grid size-10 place-items-center rounded-xl text-graphite-700 transition-colors hover:bg-ivory-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald lg:hidden"
              onClick={() => setMobileMenuOpen(true)}
              ref={menuTriggerRef}
              type="button"
            >
              <Menu aria-hidden="true" className="size-5" />
            </button>
            <button
              aria-label={
                sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'
              }
              className="hidden size-10 place-items-center rounded-xl text-graphite-600 transition-colors hover:bg-ivory-100 hover:text-graphite-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald lg:grid"
              onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
              type="button"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen aria-hidden="true" className="size-[18px]" />
              ) : (
                <PanelLeftClose aria-hidden="true" className="size-[18px]" />
              )}
            </button>
            <span className="hidden font-display text-sm font-semibold tracking-[-0.03em] text-graphite-950 sm:block lg:hidden">
              ClaimSage
            </span>
          </div>

          <div className="relative min-w-0 max-w-[560px] flex-1">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-3.5 top-1/2 size-[17px] -translate-y-1/2 text-graphite-400"
            />
            <Input
              aria-label="Search workspace"
              className="h-10 border-ivory-200 bg-white/80 pl-10 pr-10 placeholder:text-graphite-600 focus-visible:ring-emerald/50"
              placeholder="Search workspace"
              type="search"
            />
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-3">
            <span className="hidden items-center gap-2 rounded-full border border-emerald/15 bg-emerald-light px-3 py-1.5 text-[11px] font-semibold text-emerald-dark xl:inline-flex">
              <span className="size-1.5 rounded-full bg-emerald" />
              Human review required
            </span>
            <Dropdown
              label="Notifications"
              trigger={
                <span className="relative grid size-10 place-items-center rounded-xl text-graphite-600 transition-colors hover:bg-ivory-100 hover:text-graphite-950">
                  <Bell aria-hidden="true" className="size-[18px]" />
                </span>
              }
            >
              <div className="w-[min(280px,calc(100vw-2rem))] p-4">
                <p className="text-sm font-semibold text-graphite-900">
                  Notifications
                </p>
                <p className="mt-1 text-xs leading-5 text-graphite-600">
                  Notifications will appear here when available.
                </p>
              </div>
            </Dropdown>
            <Dropdown
              label="Workspace profile"
              trigger={
                <span className="flex h-10 items-center gap-2 rounded-xl border border-ivory-200 bg-white px-1.5 pr-2.5 transition-colors hover:bg-ivory-100">
                  <span className="grid size-7 place-items-center rounded-lg bg-graphite-900 font-display text-[10px] font-semibold text-ivory-50">
                    {employee ? getInitials(employee.display_name) : ''}
                  </span>
                  <span className="hidden max-w-24 truncate text-xs font-medium text-graphite-700 sm:block">
                    {employee?.display_name}
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    className="size-3.5 text-graphite-400"
                  />
                </span>
              }
            >
              <div className="w-[min(240px,calc(100vw-2rem))] p-2">
                <div className="border-b border-ivory-200 px-3 py-2">
                  <p className="text-xs font-semibold text-graphite-900">
                  {employee?.display_name}
                  </p>
                  <p className="mt-0.5 text-[11px] text-graphite-600">
                  {employee?.email}
                  </p>
                  <p className="mt-0.5 text-[11px] font-medium text-emerald-700">
                  {employee ? formatRole(employee.role) : ''}
                  </p>
                </div>
                {employee?.role?.toLowerCase() === 'admin' && (
                  <DropdownLink to="/settings">Workspace settings</DropdownLink>
                )}
                <button
                  className="mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-xs font-medium text-graphite-700 transition-colors hover:bg-ivory-100 hover:text-graphite-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
                  onClick={(event) => {
                    const details = event.currentTarget.closest('details')
                    if (details) details.open = false
                    logout()
                  }}
                  type="button"
                >
                  <LogOut aria-hidden="true" className="size-3.5" />
                  Sign out
                </button>
              </div>
            </Dropdown>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-7 sm:py-7 lg:px-9 lg:py-5">
          <Outlet />
          {currentPage && (
            <span className="sr-only" aria-live="polite">
              {currentPage.label}
            </span>
          )}
        </main>
      </div>
      </div>
    </MotionConfig>
  )
}
