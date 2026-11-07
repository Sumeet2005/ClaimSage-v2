import { forwardRef, type HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <section
      className={cn(
        'rounded-2xl border border-ivory-200 bg-white text-graphite-900 shadow-[0_6px_24px_-18px_rgba(25,28,25,0.28)]',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Card.displayName = 'Card'

export const CardHeader = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div className={cn('flex flex-col space-y-1.5 p-5 sm:p-6', className)} ref={ref} {...props} />
))
CardHeader.displayName = 'CardHeader'

export const CardTitle = forwardRef<
  HTMLHeadingElement,
  HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h2
    className={cn(
      'font-display text-base font-semibold tracking-[-0.02em] text-graphite-950',
      className,
    )}
    ref={ref}
    {...props}
  />
))
CardTitle.displayName = 'CardTitle'

export const CardDescription = forwardRef<
  HTMLParagraphElement,
  HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p className={cn('text-xs leading-5 text-graphite-500', className)} ref={ref} {...props} />
))
CardDescription.displayName = 'CardDescription'

export const CardContent = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div className={cn('p-5 pt-0 sm:p-6 sm:pt-0', className)} ref={ref} {...props} />
))
CardContent.displayName = 'CardContent'
