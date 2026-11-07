import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface BreadcrumbItem {
  label: string
  href?: string
}

export function PageContainer({
  title,
  description,
  eyebrow,
  breadcrumbs,
  actions,
  children,
  className,
}: {
  title: string
  description?: string
  eyebrow?: string
  breadcrumbs?: BreadcrumbItem[]
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  const items = breadcrumbs ?? [
    { label: 'Workspace', href: '/' },
    { label: title },
  ]

  return (
    <div className={cn('mx-auto w-full max-w-[1320px]', className)}>
      <nav aria-label="Breadcrumb" className="mb-4">
        <ol className="flex flex-wrap items-center gap-2 text-[11px] font-medium text-graphite-600">
          {items.map((item, index) => (
            <li className="flex items-center gap-2" key={`${item.label}-${index}`}>
              {index > 0 && (
                <ChevronRight
                  aria-hidden="true"
                  className="size-3 text-ivory-300"
                />
              )}
              {item.href && index < items.length - 1 ? (
                <Link
                  className="rounded-sm transition-colors hover:text-graphite-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
                  to={item.href}
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  aria-current={index === items.length - 1 ? 'page' : undefined}
                  className={
                    index === items.length - 1
                      ? 'text-graphite-700'
                      : undefined
                  }
                >
                  {item.label}
                </span>
              )}
            </li>
          ))}
        </ol>
      </nav>

      <header className="mb-6 flex flex-col gap-4 border-b border-ivory-200/80 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {eyebrow && (
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.19em] text-emerald-dark">
              {eyebrow}
            </p>
          )}
          <h1 className="font-display text-[28px] font-semibold leading-tight tracking-[-0.045em] text-graphite-950 sm:text-[34px]">
            {title}
          </h1>
          {description && (
            <p className="mt-2 max-w-2xl text-sm leading-6 text-graphite-600 sm:text-[15px]">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {children}
    </div>
  )
}
