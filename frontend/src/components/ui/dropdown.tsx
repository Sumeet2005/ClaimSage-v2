import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

export function Dropdown({
  label,
  trigger,
  children,
  className,
}: {
  label: string
  trigger: ReactNode
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDetailsElement>(null)
  const triggerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
        if (rootRef.current) rootRef.current.open = false
      }
    }
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        if (rootRef.current) rootRef.current.open = false
        triggerRef.current?.focus()
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  return (
    <details
      className={cn('group relative', className)}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      ref={rootRef}
    >
      <summary
        aria-label={label}
        aria-expanded={open}
        className="list-none cursor-pointer rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald focus-visible:ring-offset-2 focus-visible:ring-offset-ivory-50 [&::-webkit-details-marker]:hidden"
        ref={triggerRef}
      >
        {trigger}
      </summary>
      <div className="absolute right-0 top-[calc(100%+0.65rem)] z-50 overflow-hidden rounded-2xl border border-ivory-200 bg-white text-graphite-900 shadow-[0_18px_50px_-22px_rgba(25,28,25,0.42)]">
        {children}
      </div>
    </details>
  )
}

export function DropdownLink({
  to,
  children,
}: {
  to: string
  children: ReactNode
}) {
  return (
    <Link
      className="mt-1 block rounded-xl px-3 py-2.5 text-xs font-medium text-graphite-700 transition-colors hover:bg-ivory-100 hover:text-graphite-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
      onClick={(event) => {
        const details = event.currentTarget.closest('details')
        if (details) details.open = false
      }}
      to={to}
    >
      {children}
    </Link>
  )
}
