import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-[0.04em]',
  {
    variants: {
      variant: {
        default: 'bg-emerald-light text-emerald-dark',
        secondary: 'bg-ivory-100 text-graphite-700',
        outline: 'border border-ivory-300 bg-white/70 text-graphite-700',
        accent: 'bg-champagne-light text-graphite-700',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span
      className={cn(badgeVariants({ className, variant }))}
      ref={ref}
      {...props}
    />
  ),
)
Badge.displayName = 'Badge'
