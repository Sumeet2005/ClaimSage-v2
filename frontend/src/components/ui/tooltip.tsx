import { useId, type ReactNode } from 'react'

export function Tooltip({
  label,
  children,
}: {
  label: string
  children: (props: { 'aria-describedby': string }) => ReactNode
}) {
  const id = useId()

  return (
    <span className="group relative block">
      {children({ 'aria-describedby': id })}
      <span
        className="pointer-events-none absolute left-[calc(100%+0.65rem)] top-1/2 z-50 hidden -translate-y-1/2 whitespace-nowrap rounded-lg border border-graphite-700 bg-graphite-900 px-2.5 py-1.5 text-xs font-medium text-ivory-50 opacity-0 shadow-xl transition-opacity group-hover:block group-hover:opacity-100 group-focus-within:block group-focus-within:opacity-100"
        id={id}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  )
}
