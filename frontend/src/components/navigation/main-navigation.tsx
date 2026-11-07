import { NavLink } from 'react-router-dom'
import type { NavigationItem } from '@/components/navigation/navigation-items'
import { navigationItems } from '@/components/navigation/navigation-items'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useAuth } from '@/features/auth/auth-context'

function NavigationLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavigationItem
  collapsed: boolean
  onNavigate?: () => void
}) {
  const Icon = item.icon
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex min-h-11 items-center gap-3 rounded-xl text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ivory-50 focus-visible:ring-offset-2 focus-visible:ring-offset-graphite-950',
      collapsed ? 'justify-center px-0' : 'px-3',
      isActive
        ? 'bg-white/[0.095] text-ivory-50 shadow-[inset_2px_0_0_var(--color-champagne)]'
        : 'text-graphite-400 hover:bg-white/[0.09] hover:text-ivory-50',
    )

  const content = (
    describedBy?: { 'aria-describedby': string },
  ) => (
    <NavLink
      aria-label={collapsed ? item.label : undefined}
      className={linkClass}
      end={item.href === '/dashboard' || item.href === '/'}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      to={item.href}
      {...describedBy}
    >
      <Icon aria-hidden="true" className="size-[17px] shrink-0" strokeWidth={1.8} />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  )

  return collapsed ? (
    <Tooltip label={item.label}>{(props) => content(props)}</Tooltip>
  ) : (
    content()
  )
}

export function MainNavigation({
  collapsed,
  className,
  onNavigate,
}: {
  collapsed: boolean
  className?: string
  onNavigate?: () => void
}) {
  const { employee } = useAuth()
  const isAdmin = employee?.role?.toLowerCase() === 'admin'

  const workspaceItems = navigationItems.filter(
    (item) => item.group === 'workspace',
  )
  const administrationItems = navigationItems.filter(
    (item) => item.group === 'administration',
  )

  return (
    <nav aria-label="Main navigation" className={cn('space-y-6', className)}>
      <div>
        {!collapsed && (
          <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-graphite-400">
            Workspace
          </p>
        )}
        <div className="space-y-1">
          {workspaceItems.map((item) => (
            <NavigationLink
              collapsed={collapsed}
              item={item}
              key={item.href}
              {...(onNavigate ? { onNavigate } : {})}
            />
          ))}
        </div>
      </div>
      {isAdmin && (
        <div>
          {!collapsed && (
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-graphite-400">
              Administration
            </p>
          )}
          <div className="space-y-1">
            {administrationItems.map((item) => (
              <NavigationLink
                collapsed={collapsed}
                item={item}
                key={item.href}
                {...(onNavigate ? { onNavigate } : {})}
              />
            ))}
          </div>
        </div>
      )}
    </nav>
  )
}
