import * as LabelPrimitive from '@radix-ui/react-label'
import { forwardRef, type ComponentRef, type ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/utils'

export type LabelProps = ComponentPropsWithoutRef<typeof LabelPrimitive.Root>

export const Label = forwardRef<ComponentRef<typeof LabelPrimitive.Root>, LabelProps>(
  ({ className, ...props }, ref) => (
    <LabelPrimitive.Root
      className={cn(
        'text-sm font-medium leading-none text-graphite-800 peer-disabled:cursor-not-allowed peer-disabled:opacity-60',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Label.displayName = LabelPrimitive.Root.displayName
